#requires -Version 7.0
# Wrapper entrypoints emit their final JSON and diagnostics through
# Console.Out/Error.  Make that boundary UTF-8 before any core function can
# write, without using the strict file-decoding helper or a global preference.
$script:AwConsoleUtf8 = [System.Text.UTF8Encoding]::new($false)
try { [Console]::OutputEncoding = $script:AwConsoleUtf8 } catch { }
try { [Console]::InputEncoding = $script:AwConsoleUtf8 } catch { }

Set-StrictMode -Version Latest

function Get-AwUtf8 {
    [System.Text.UTF8Encoding]::new($false, $true)
}

function Initialize-AwJobType {
    if (-not $IsWindows) { throw 'WINDOWS_JOB_OBJECT_REQUIRED' }
    if ($null -ne ('AwJobHandle' -as [type])) { return }
    $source = @'
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

public sealed class AwJobHandle : IDisposable
{
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private IntPtr handle;

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
        public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct BASIC_LIMITS
    {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct EXTENDED_LIMITS
    {
        public BASIC_LIMITS BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct BASIC_ACCOUNTING
    {
        public long TotalUserTime, TotalKernelTime, ThisPeriodTotalUserTime, ThisPeriodTotalKernelTime;
        public uint TotalPageFaultCount, TotalProcesses, ActiveProcesses, TotalTerminatedProcesses;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref EXTENDED_LIMITS info, uint length);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool QueryInformationJobObject(IntPtr job, int infoClass, out BASIC_ACCOUNTING info, uint length, IntPtr returnLength);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool TerminateJobObject(IntPtr job, uint exitCode);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    public AwJobHandle()
    {
        handle = CreateJobObject(IntPtr.Zero, null);
        if (handle == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        EXTENDED_LIMITS limits = new EXTENDED_LIMITS();
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if (!SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf(typeof(EXTENDED_LIMITS))))
        {
            int error = Marshal.GetLastWin32Error();
            CloseHandle(handle);
            handle = IntPtr.Zero;
            throw new Win32Exception(error);
        }
    }

    public void Assign(Process process)
    {
        if (!AssignProcessToJobObject(handle, process.Handle))
            throw new Win32Exception(Marshal.GetLastWin32Error());
    }

    public bool IsEmpty()
    {
        BASIC_ACCOUNTING accounting;
        if (!QueryInformationJobObject(handle, 1, out accounting, (uint)Marshal.SizeOf(typeof(BASIC_ACCOUNTING)), IntPtr.Zero))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        return accounting.ActiveProcesses == 0;
    }

    public bool TerminateAndWait(int milliseconds)
    {
        if (!TerminateJobObject(handle, 126)) return false;
        Stopwatch clock = Stopwatch.StartNew();
        while (clock.ElapsedMilliseconds < milliseconds)
        {
            if (IsEmpty()) return true;
            Thread.Sleep(10);
        }
        return IsEmpty();
    }

    public void Dispose()
    {
        if (handle != IntPtr.Zero)
        {
            CloseHandle(handle);
            handle = IntPtr.Zero;
        }
        GC.SuppressFinalize(this);
    }

    ~AwJobHandle() { Dispose(); }
}

public static class AwFileLinks
{
    [StructLayout(LayoutKind.Sequential)]
    private struct BY_HANDLE_FILE_INFORMATION
    {
        public uint FileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateFile(string path, uint access, FileShare share, IntPtr security,
        FileMode creation, uint flags, IntPtr template);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(IntPtr handle, out BY_HANDLE_FILE_INFORMATION information);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    public static uint GetLinkCount(string path)
    {
        IntPtr handle = CreateFile(path, 0, FileShare.ReadWrite | FileShare.Delete, IntPtr.Zero,
            FileMode.Open, 0x02000000, IntPtr.Zero);
        if (handle == new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            BY_HANDLE_FILE_INFORMATION information;
            if (!GetFileInformationByHandle(handle, out information))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            return information.NumberOfLinks;
        }
        finally { CloseHandle(handle); }
    }
}

public sealed class AwRepositoryWatcher : IDisposable
{
    private readonly List<FileSystemWatcher> watchers = new List<FileSystemWatcher>();
    private readonly ConcurrentDictionary<string, byte> paths = new ConcurrentDictionary<string, byte>(StringComparer.OrdinalIgnoreCase);
    private readonly ConcurrentQueue<string> errorMessages = new ConcurrentQueue<string>();
    private int errors;
    private int activeCallbacks;
    private long sequence;
    private bool disposed;

    public AwRepositoryWatcher(string[] roots)
    {
        HashSet<string> unique = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string root in roots)
        {
            string full = Path.GetFullPath(root);
            if (!unique.Add(full)) continue;
            FileSystemWatcher watcher = new FileSystemWatcher(full);
            watcher.IncludeSubdirectories = true;
            watcher.InternalBufferSize = 65536;
            watcher.NotifyFilter = NotifyFilters.FileName | NotifyFilters.DirectoryName |
                NotifyFilters.LastWrite | NotifyFilters.Size;
            watcher.Changed += OnChanged;
            watcher.Created += OnChanged;
            watcher.Deleted += OnChanged;
            watcher.Renamed += OnRenamed;
            watcher.Error += OnError;
            watcher.EnableRaisingEvents = true;
            watchers.Add(watcher);
        }
        if (watchers.Count == 0) throw new InvalidOperationException("No watcher roots.");
    }

    private void OnChanged(object sender, FileSystemEventArgs args)
    {
        System.Threading.Interlocked.Increment(ref activeCallbacks);
        try
        {
            if (!String.IsNullOrWhiteSpace(args.FullPath)) paths.TryAdd(args.FullPath, 0);
            System.Threading.Interlocked.Increment(ref sequence);
        }
        finally { System.Threading.Interlocked.Decrement(ref activeCallbacks); }
    }

    private void OnRenamed(object sender, RenamedEventArgs args)
    {
        System.Threading.Interlocked.Increment(ref activeCallbacks);
        try
        {
            if (!String.IsNullOrWhiteSpace(args.OldFullPath)) paths.TryAdd(args.OldFullPath, 0);
            if (!String.IsNullOrWhiteSpace(args.FullPath)) paths.TryAdd(args.FullPath, 0);
            System.Threading.Interlocked.Increment(ref sequence);
        }
        finally { System.Threading.Interlocked.Decrement(ref activeCallbacks); }
    }

    private void OnError(object sender, ErrorEventArgs args)
    {
        Exception exception = args.GetException();
        errorMessages.Enqueue(exception == null
            ? "FILESYSTEM_WATCHER_ERROR"
            : exception.GetType().FullName + ": " + exception.Message);
        System.Threading.Interlocked.Increment(ref errors);
        System.Threading.Interlocked.Increment(ref sequence);
    }

    public string[] StopAndGetPaths()
    {
        System.Threading.Thread.Sleep(50);
        foreach (FileSystemWatcher watcher in watchers) watcher.EnableRaisingEvents = false;
        DisposeWatchers();
        long previous = System.Threading.Interlocked.Read(ref sequence);
        int quietSamples = 0;
        for (int attempt = 0; attempt < 40; attempt++)
        {
            System.Threading.Thread.Sleep(25);
            long current = System.Threading.Interlocked.Read(ref sequence);
            if (System.Threading.Volatile.Read(ref activeCallbacks) == 0 && current == previous) quietSamples++;
            else quietSamples = 0;
            previous = current;
            if (quietSamples >= 4) break;
        }
        if (quietSamples < 4 || System.Threading.Volatile.Read(ref activeCallbacks) != 0)
        {
            errorMessages.Enqueue("CALLBACK_DRAIN_TIMEOUT");
            System.Threading.Interlocked.Increment(ref errors);
        }
        string[] result = new string[paths.Count];
        paths.Keys.CopyTo(result, 0);
        return result;
    }

    public bool HasError { get { return errors != 0; } }
    public int ErrorCount { get { return System.Threading.Volatile.Read(ref errors); } }
    public string[] GetErrors() { return errorMessages.ToArray(); }

    public void Dispose()
    {
        DisposeWatchers();
    }

    private void DisposeWatchers()
    {
        if (disposed) return;
        disposed = true;
        foreach (FileSystemWatcher watcher in watchers)
        {
            watcher.EnableRaisingEvents = false;
            watcher.Dispose();
        }
        watchers.Clear();
    }
}
'@
    try { [void](Add-Type -TypeDefinition $source -Language CSharp -ErrorAction Stop) }
    catch { throw 'WINDOWS_JOB_OBJECT_INIT_FAILED' }
}

function Read-AwConfig {
    param([Parameter(Mandatory)][string]$Path)

    try { $full = [System.IO.Path]::GetFullPath($Path) }
    catch { throw 'CONFIG_PATH_INVALID' }
    if (-not [System.IO.File]::Exists($full)) { throw 'CONFIG_NOT_FOUND' }

    try {
        $raw = [System.IO.File]::ReadAllText($full, (Get-AwUtf8))
        $config = $raw | ConvertFrom-Json -Depth 10 -ErrorAction Stop
    }
    catch { throw 'CONFIG_INVALID_JSON_OR_UTF8' }

    if ($null -eq $config -or $config -is [array] -or $config -is [string]) { throw 'CONFIG_ROOT_INVALID' }

    $required = @(
        'schemaVersion', 'repositoryRoot', 'activeMachineProfile', 'machineProfiles',
        'preflightTimeoutSeconds', 'grokTimeoutSeconds', 'opusTimeoutSeconds',
        'codexTimeoutSeconds', 'maxOutputBytes'
    )
    foreach ($name in $required) {
        if ($null -eq $config.PSObject.Properties[$name]) { throw ('CONFIG_FIELD_MISSING_' + $name.ToUpperInvariant()) }
    }
    try { $schemaVersion = [int]$config.schemaVersion }
    catch { throw 'CONFIG_SCHEMA_INVALID' }
    if ($schemaVersion -ne 3) { throw 'CONFIG_SCHEMA_UNSUPPORTED' }

    try { $preflightTimeout = [int]$config.preflightTimeoutSeconds }
    catch { throw 'CONFIG_PREFLIGHT_TIMEOUT_INVALID' }
    if ($preflightTimeout -ne 30) { throw 'CONFIG_PREFLIGHT_TIMEOUT_INVALID' }
    $config.preflightTimeoutSeconds = $preflightTimeout

    $configuredRoot = [string]$config.repositoryRoot
    if (-not [System.IO.Path]::IsPathFullyQualified($configuredRoot)) { throw 'CONFIG_REPOSITORY_NOT_ABSOLUTE' }
    try { $root = [System.IO.Path]::GetFullPath($configuredRoot) }
    catch { throw 'CONFIG_REPOSITORY_INVALID' }
    $config.repositoryRoot = $root

    if ($config.machineProfiles -is [array] -or $config.machineProfiles -is [string] -or $null -eq $config.machineProfiles) {
        throw 'CONFIG_MACHINE_PROFILES_INVALID'
    }
    $activeProfile = [string]$config.activeMachineProfile
    if ($activeProfile -notmatch '^[A-Za-z0-9_-]+$') { throw 'CONFIG_ACTIVE_MACHINE_PROFILE_INVALID' }
    if ($null -eq $config.machineProfiles.PSObject.Properties[$activeProfile]) { throw 'CONFIG_ACTIVE_MACHINE_PROFILE_MISSING' }
    foreach ($profileProperty in $config.machineProfiles.PSObject.Properties) {
        $profileName = [string]$profileProperty.Name
        $profile = $profileProperty.Value
        if ($profileName -notmatch '^[A-Za-z0-9_-]+$' -or $null -eq $profile -or $profile -is [array] -or $profile -is [string]) {
            throw 'CONFIG_MACHINE_PROFILE_INVALID'
        }
        foreach ($field in @('grokExecutable', 'opusExecutable', 'codexExecutable')) {
            if ($null -eq $profile.PSObject.Properties[$field]) { throw ('CONFIG_MACHINE_PROFILE_FIELD_MISSING_' + $field.ToUpperInvariant()) }
        }
    }

    foreach ($name in @('grokTimeoutSeconds', 'opusTimeoutSeconds', 'codexTimeoutSeconds')) {
        try { $value = [int]$config.$name }
        catch { throw ('CONFIG_TIMEOUT_INVALID_' + $name.ToUpperInvariant()) }
        if ($value -lt 1 -or $value -gt 86400) { throw ('CONFIG_TIMEOUT_INVALID_' + $name.ToUpperInvariant()) }
        $config.$name = $value
    }
    try { $cap = [int64]$config.maxOutputBytes }
    catch { throw 'CONFIG_OUTPUT_CAP_INVALID' }
    if ($cap -lt 65536 -or $cap -gt 67108864) { throw 'CONFIG_OUTPUT_CAP_INVALID' }
    $config.maxOutputBytes = $cap
    return $config
}

function Resolve-AwRepositoryRoot {
    param(
        [Parameter(Mandatory)][string]$ConfiguredRoot,
        [AllowEmptyString()][string]$RepositoryRoot = ''
    )
    $selected = if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) { $ConfiguredRoot } else { $RepositoryRoot }
    if (-not [System.IO.Path]::IsPathFullyQualified($selected)) { throw 'REPOSITORY_ROOT_NOT_ABSOLUTE' }
    try { $full = [System.IO.Path]::GetFullPath($selected) }
    catch { throw 'REPOSITORY_ROOT_INVALID' }
    if (-not [System.IO.Directory]::Exists($full)) { throw 'REPOSITORY_ROOT_MISSING' }

    $identity = Get-AwGitRepositoryIdentity -Root $full
    if (-not $identity.TopLevel.Equals($full, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'REPOSITORY_ROOT_MUST_BE_GIT_TOPLEVEL'
    }
    return $identity.TopLevel
}

function Expand-AwExecutablePathTemplate {
    param(
        [Parameter(Mandatory)][string]$Template,
        [Parameter(Mandatory)][ValidateSet('Grok', 'Opus', 'Codex')][string]$Provider
    )

    $expanded = $Template
    $supported = [ordered]@{
        '%USERPROFILE%' = 'USERPROFILE'
        '%APPDATA%' = 'APPDATA'
        '%LOCALAPPDATA%' = 'LOCALAPPDATA'
    }
    foreach ($entry in $supported.GetEnumerator()) {
        $token = [string]$entry.Key
        $environmentName = [string]$entry.Value
        $index = $expanded.IndexOf($token, [System.StringComparison]::OrdinalIgnoreCase)
        if ($index -lt 0) { continue }
        $value = [System.Environment]::GetEnvironmentVariable(
            $environmentName, [System.EnvironmentVariableTarget]::Process
        )
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw ('CONFIG_' + $Provider.ToUpperInvariant() + '_EXECUTABLE_ENVIRONMENT_MISSING_' + $environmentName)
        }
        while ($index -ge 0) {
            $expanded = $expanded.Substring(0, $index) + $value + $expanded.Substring($index + $token.Length)
            $index = $expanded.IndexOf($token, [System.StringComparison]::OrdinalIgnoreCase)
        }
    }
    if ([regex]::IsMatch($expanded, '%[A-Za-z0-9_()]+%')) {
        throw ('CONFIG_' + $Provider.ToUpperInvariant() + '_EXECUTABLE_ENVIRONMENT_VARIABLE_UNSUPPORTED')
    }
    return $expanded
}

function Resolve-AwProviderExecutable {
    param(
        [Parameter(Mandatory)]$Config,
        [Parameter(Mandatory)][ValidateSet('Grok', 'Opus', 'Codex')][string]$Provider,
        [AllowEmptyString()][string]$MachineProfile = ''
    )
    $selected = if ([string]::IsNullOrWhiteSpace($MachineProfile)) {
        [string]$Config.activeMachineProfile
    }
    else { $MachineProfile }
    if ($selected -notmatch '^[A-Za-z0-9_-]+$') { throw 'CONFIG_MACHINE_PROFILE_NAME_INVALID' }
    $property = $Config.machineProfiles.PSObject.Properties[$selected]
    if ($null -eq $property) { throw 'CONFIG_MACHINE_PROFILE_NOT_FOUND' }
    $field = switch ($Provider) {
        'Grok' { 'grokExecutable' }
        'Opus' { 'opusExecutable' }
        default { 'codexExecutable' }
    }
    $configured = [string]$property.Value.$field
    if ([string]::IsNullOrWhiteSpace($configured)) { throw ('CONFIG_' + $Provider.ToUpperInvariant() + '_EXECUTABLE_NOT_SET_FOR_' + $selected.ToUpperInvariant()) }
    $configured = Expand-AwExecutablePathTemplate -Template $configured -Provider $Provider
    if (-not [System.IO.Path]::IsPathFullyQualified($configured)) { throw ('CONFIG_' + $Provider.ToUpperInvariant() + '_EXECUTABLE_NOT_ABSOLUTE') }
    try { $full = [System.IO.Path]::GetFullPath($configured) }
    catch { throw ('CONFIG_' + $Provider.ToUpperInvariant() + '_EXECUTABLE_INVALID') }
    if (-not $full.EndsWith('.exe', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw ('CONFIG_' + $Provider.ToUpperInvariant() + '_NATIVE_EXECUTABLE_MISSING')
    }
    if ([System.IO.File]::Exists($full)) { return $full }
    if ($Provider -eq 'Codex') {
        $recovered = Resolve-AwCodexAutoUpdatedExecutable -ConfiguredPath $full
        if (-not [string]::IsNullOrWhiteSpace($recovered)) {
            [Console]::Error.WriteLine('CODEX_EXECUTABLE_AUTO_RECOVERED=' + $recovered)
            return $recovered
        }
    }
    throw ('CONFIG_' + $Provider.ToUpperInvariant() + '_NATIVE_EXECUTABLE_MISSING')
}

function Resolve-AwCodexAutoUpdatedExecutable {
    param(
        [Parameter(Mandatory)][string]$ConfiguredPath,
        [AllowEmptyString()][string]$LocalAppDataRoot = ''
    )

    if ([string]::IsNullOrWhiteSpace($LocalAppDataRoot)) {
        $LocalAppDataRoot = [System.Environment]::GetEnvironmentVariable(
            'LOCALAPPDATA', [System.EnvironmentVariableTarget]::Process
        )
    }
    if ([string]::IsNullOrWhiteSpace($LocalAppDataRoot) -or
        -not [System.IO.Path]::IsPathFullyQualified($LocalAppDataRoot)) { return '' }
    try {
        $configuredFull = [System.IO.Path]::GetFullPath($ConfiguredPath)
        $localRoot = [System.IO.Path]::GetFullPath($LocalAppDataRoot)
        $binRoot = [System.IO.Path]::GetFullPath((Join-Path $localRoot 'OpenAI\Codex\bin'))
        $configuredDirectory = [System.IO.Path]::GetDirectoryName($configuredFull)
        $configuredBin = [System.IO.Path]::GetDirectoryName($configuredDirectory)
    }
    catch { return '' }
    if ([System.IO.Path]::GetFileName($configuredFull) -cne 'codex.exe' -or
        -not $configuredBin.Equals($binRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        [System.IO.Path]::GetFileName($configuredDirectory) -notmatch '^[0-9A-Fa-f]{16}$' -or
        -not [System.IO.Directory]::Exists($binRoot)) { return '' }

    $candidates = [System.Collections.Generic.List[System.IO.FileInfo]]::new()
    try {
        foreach ($directoryPath in [System.IO.Directory]::EnumerateDirectories($binRoot)) {
            $directory = [System.IO.DirectoryInfo]::new($directoryPath)
            if ($directory.Name -notmatch '^[0-9A-Fa-f]{16}$' -or
                ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
            $candidatePath = Join-Path $directory.FullName 'codex.exe'
            if (-not [System.IO.File]::Exists($candidatePath)) { continue }
            $candidate = [System.IO.FileInfo]::new($candidatePath)
            if (($candidate.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
            [void]$candidates.Add($candidate)
        }
    }
    catch { return '' }
    if ($candidates.Count -eq 0) { return '' }
    $selected = $candidates | Sort-Object `
        @{ Expression = { $_.LastWriteTimeUtc }; Descending = $true }, `
        @{ Expression = { $_.FullName }; Descending = $true } | Select-Object -First 1
    return [System.IO.Path]::GetFullPath([string]$selected.FullName)
}

function Read-AwPrompt {
    param(
        [AllowEmptyString()][string]$Prompt = '',
        [AllowEmptyString()][string]$PromptFile = ''
    )

    $hasText = -not [string]::IsNullOrWhiteSpace($Prompt)
    $hasFile = -not [string]::IsNullOrWhiteSpace($PromptFile)
    if ($hasText -eq $hasFile) { throw 'PROMPT_OR_PROMPT_FILE_REQUIRED' }
    if ($hasFile) {
        try { $full = [System.IO.Path]::GetFullPath($PromptFile) }
        catch { throw 'PROMPT_FILE_INVALID' }
        if (-not [System.IO.File]::Exists($full)) { throw 'PROMPT_FILE_MISSING' }
        try { $Prompt = [System.IO.File]::ReadAllText($full, (Get-AwUtf8)) }
        catch { throw 'PROMPT_FILE_INVALID_UTF8' }
    }
    if ([string]::IsNullOrWhiteSpace($Prompt)) { throw 'PROMPT_EMPTY' }
    if ($Prompt.IndexOf([char]0) -ge 0) { throw 'PROMPT_CONTAINS_NUL' }
    return [string]$Prompt
}

function Get-AwTempBase {
    $localAppData = [System.Environment]::GetEnvironmentVariable('LOCALAPPDATA', [System.EnvironmentVariableTarget]::Process)
    if ([string]::IsNullOrWhiteSpace($localAppData) -or -not [System.IO.Path]::IsPathFullyQualified($localAppData)) {
        throw 'TEMP_BASE_LOCALAPPDATA_INVALID'
    }
    try {
        $localRoot = [System.IO.Path]::GetFullPath($localAppData).TrimEnd([char]'\', [char]'/')
        $base = [System.IO.Path]::GetFullPath((Join-Path $localRoot 'Temp'))
    }
    catch { throw 'TEMP_BASE_LOCALAPPDATA_INVALID' }
    $localPrefix = $localRoot + [System.IO.Path]::DirectorySeparatorChar
    if (-not $base.StartsWith($localPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
        [System.IO.Path]::GetFileName($base) -cne 'Temp') {
        throw 'TEMP_BASE_BOUNDARY_INVALID'
    }
    try { [void][System.IO.Directory]::CreateDirectory($base) }
    catch { throw 'TEMP_BASE_UNAVAILABLE' }
    if (-not [System.IO.Directory]::Exists($base)) { throw 'TEMP_BASE_UNAVAILABLE' }
    return $base
}

function New-AwTempDirectory {
    param(
        [Parameter(Mandatory)][string]$Prefix,
        [AllowEmptyString()][string]$Base = ''
    )
    if ([string]::IsNullOrWhiteSpace($Base)) { $Base = Get-AwTempBase }
    try { $base = [System.IO.Path]::GetFullPath($Base) }
    catch { throw 'TEMP_BASE_INVALID' }
    if (-not $base.Equals((Get-AwTempBase), [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'TEMP_BASE_NOT_CANONICAL'
    }
    $path = Join-Path $base ($Prefix + [guid]::NewGuid().ToString('N'))
    [void][System.IO.Directory]::CreateDirectory($path)
    return [System.IO.Path]::GetFullPath($path)
}

function Remove-AwTempDirectory {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Prefix,
        [AllowEmptyString()][string]$Base = ''
    )
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    if ([string]::IsNullOrWhiteSpace($Base)) { throw 'TEMP_CLEANUP_BASE_REQUIRED' }
    try { $base = [System.IO.Path]::GetFullPath($Base) }
    catch { throw 'TEMP_CLEANUP_BASE_INVALID' }
    $full = [System.IO.Path]::GetFullPath($Path)
    $basePrefix = $base.TrimEnd([char]'\', [char]'/') + [System.IO.Path]::DirectorySeparatorChar
    if (-not $full.StartsWith($basePrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not [System.IO.Path]::GetFileName($full).StartsWith($Prefix, [System.StringComparison]::Ordinal)) {
        throw 'TEMP_CLEANUP_BOUNDARY_VIOLATION'
    }
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        if (-not [System.IO.Directory]::Exists($full)) { return }
        try { [System.IO.Directory]::Delete($full, $true) } catch { }
        if (-not [System.IO.Directory]::Exists($full)) { return }
        if ($attempt -lt 2) { Start-Sleep -Milliseconds (50 * ($attempt + 1)) }
    }
    throw 'TEMP_CLEANUP_FAILED'
}

function Write-AwUtf8File {
    param([Parameter(Mandatory)][string]$Path, [AllowEmptyString()][string]$Text = '')
    [System.IO.File]::WriteAllText($Path, $Text, (Get-AwUtf8))
}

function New-AwProviderEnvironment {
    param(
        [Parameter(Mandatory)][ValidateSet('Grok', 'Opus', 'Codex')][string]$Provider,
        [hashtable]$Overrides = @{}
    )
    $providerNames = switch ($Provider) {
        'Grok' { @('XAI_API_KEY', 'GROK_API_KEY', 'XAI_TOKEN', 'GROK_TOKEN') }
        'Opus' { @('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN') }
        default { @('OPENAI_API_KEY', 'CODEX_API_KEY') }
    }
    $safeNames = @(
        'ALLUSERSPROFILE', 'APPDATA', 'CommonProgramFiles', 'CommonProgramFiles(x86)',
        'CommonProgramW6432', 'COMPUTERNAME', 'ComSpec', 'DriverData', 'HOME',
        'HOMEDRIVE', 'HOMEPATH', 'LOCALAPPDATA', 'NUMBER_OF_PROCESSORS', 'OS',
        'Path', 'PATHEXT', 'PROCESSOR_ARCHITECTURE', 'PROCESSOR_IDENTIFIER',
        'PROCESSOR_LEVEL', 'PROCESSOR_REVISION', 'ProgramData', 'ProgramFiles',
        'ProgramFiles(x86)', 'ProgramW6432', 'PUBLIC', 'SystemDrive',
        'SystemRoot', 'USERDOMAIN', 'USERDOMAIN_ROAMINGPROFILE',
        'USERNAME', 'USERPROFILE', 'windir',
        'LANG', 'LC_ALL', 'LC_CTYPE', 'TERM', 'COLORTERM', 'NO_COLOR',
        'JAVA_HOME', 'JDK_HOME', 'DOTNET_ROOT', 'DOTNET_ROOT_X64',
        'NVM_HOME', 'NVM_SYMLINK', 'PNPM_HOME', 'CARGO_HOME', 'RUSTUP_HOME',
        'GOPATH', 'GOROOT', 'PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV',
        'SSL_CERT_FILE', 'SSL_CERT_DIR', 'NODE_EXTRA_CA_CERTS'
    )
    $providerHomeNames = switch ($Provider) {
        'Grok' { @('GROK_HOME') }
        'Opus' { @('CLAUDE_CONFIG_DIR') }
        default { @('CODEX_HOME') }
    }
    $allowed = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($name in @($safeNames + $providerNames + $providerHomeNames)) { [void]$allowed.Add($name) }
    $result = @{}
    foreach ($entry in [System.Environment]::GetEnvironmentVariables().GetEnumerator()) {
        $name = [string]$entry.Key
        if ($allowed.Contains($name)) { $result[$name] = [string]$entry.Value }
    }
    foreach ($name in $Overrides.Keys) { $result[[string]$name] = $Overrides[$name] }
    $tempBase = Get-AwTempBase
    $result['TEMP'] = $tempBase
    $result['TMP'] = $tempBase
    $result['GIT_OPTIONAL_LOCKS'] = '0'
    $result['GIT_TERMINAL_PROMPT'] = '0'
    $result['GCM_INTERACTIVE'] = 'never'
    [void]$result.Remove('PSModulePath')
    return $result
}

function New-AwGitEnvironment {
    $result = @{}
    foreach ($name in @(
        'APPDATA', 'ComSpec', 'HOME', 'HOMEDRIVE', 'HOMEPATH', 'LOCALAPPDATA',
        'Path', 'PATHEXT', 'SystemDrive', 'SystemRoot', 'USERPROFILE', 'windir'
    )) {
        $value = [System.Environment]::GetEnvironmentVariable($name, [System.EnvironmentVariableTarget]::Process)
        if ($null -ne $value) { $result[$name] = $value }
    }
    $tempBase = Get-AwTempBase
    $result['TEMP'] = $tempBase
    $result['TMP'] = $tempBase
    $result['GIT_OPTIONAL_LOCKS'] = '0'
    $result['GIT_TERMINAL_PROMPT'] = '0'
    $result['GCM_INTERACTIVE'] = 'never'
    return $result
}

function Resolve-AwGitExecutable {
    try { $commands = @(Get-Command git.exe -CommandType Application -ErrorAction Stop) }
    catch { throw 'GIT_EXECUTABLE_MISSING' }
    if ($commands.Count -eq 0) { throw 'GIT_EXECUTABLE_MISSING' }
    try { $full = [System.IO.Path]::GetFullPath([string]$commands[0].Source) }
    catch { throw 'GIT_EXECUTABLE_INVALID' }
    if (-not [System.IO.File]::Exists($full) -or
        -not $full.EndsWith('.exe', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'GIT_EXECUTABLE_INVALID'
    }
    return $full
}

function Invoke-AwGitReadOnly {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Arguments,
        [Parameter(Mandatory)][string]$FailureCode
    )
    $git = Resolve-AwGitExecutable
    $gitArguments = @(
        '-c', 'core.fsmonitor=false',
        '-c', 'core.untrackedCache=false',
        '-C', $Root
    ) + @($Arguments)
    try {
        $result = Invoke-AwNativeOnce -Executable $git -Arguments $gitArguments `
            -WorkingDirectory $Root -TimeoutSeconds 30 -MaxOutputBytes 67108864 `
            -Environment (New-AwGitEnvironment)
    }
    catch { throw $FailureCode }
    if ([int]$result.ExitCode -ne 0) { throw $FailureCode }
    return [string]$result.StdOut
}

function Get-AwGitRepositoryIdentity {
    param([Parameter(Mandatory)][string]$Root)
    $text = Invoke-AwGitReadOnly -Root $Root -FailureCode 'REPOSITORY_ROOT_GIT_REV_PARSE_FAILED' -Arguments @(
        'rev-parse', '--path-format=absolute', '--show-toplevel', '--git-dir', '--git-common-dir'
    )
    $lines = @($text -split "\r?\n" | Where-Object { $_.Length -gt 0 })
    if ($lines.Count -ne 3) { throw 'REPOSITORY_ROOT_GIT_REV_PARSE_INVALID' }
    try {
        $topLevel = [System.IO.Path]::GetFullPath([string]$lines[0])
        $gitDirectory = [System.IO.Path]::GetFullPath([string]$lines[1])
        $gitCommonDirectory = [System.IO.Path]::GetFullPath([string]$lines[2])
    }
    catch { throw 'REPOSITORY_ROOT_GIT_REV_PARSE_INVALID' }
    if (-not [System.IO.Directory]::Exists($topLevel) -or
        -not [System.IO.Directory]::Exists($gitDirectory) -or
        -not [System.IO.Directory]::Exists($gitCommonDirectory)) {
        throw 'REPOSITORY_ROOT_GIT_METADATA_MISSING'
    }
    return [pscustomobject]@{
        TopLevel = $topLevel
        GitDirectory = $gitDirectory
        GitCommonDirectory = $gitCommonDirectory
    }
}

function ConvertTo-AwRepositoryRelativePath {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$FailurePrefix,
        [switch]$RequireRelative
    )
    if ([string]::IsNullOrWhiteSpace($Path) -or $Path.IndexOf([char]0) -ge 0) {
        throw ($FailurePrefix + '_INVALID')
    }
    if ($RequireRelative -and [System.IO.Path]::IsPathFullyQualified($Path)) {
        throw ($FailurePrefix + '_MUST_BE_RELATIVE')
    }
    try {
        $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd([char]'\', [char]'/')
        $candidate = if ([System.IO.Path]::IsPathFullyQualified($Path)) {
            [System.IO.Path]::GetFullPath($Path)
        }
        else { [System.IO.Path]::GetFullPath((Join-Path $rootFull $Path)) }
    }
    catch { throw ($FailurePrefix + '_INVALID') }
    $rootPrefix = $rootFull + [System.IO.Path]::DirectorySeparatorChar
    if ($candidate.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw ($FailurePrefix + '_ROOT_FORBIDDEN')
    }
    if (-not $candidate.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw ($FailurePrefix + '_OUTSIDE_REPOSITORY')
    }
    try { $relative = [System.IO.Path]::GetRelativePath($rootFull, $candidate).Replace('\', '/') }
    catch { throw ($FailurePrefix + '_INVALID') }
    if ([string]::IsNullOrWhiteSpace($relative) -or $relative -eq '.' -or
        $relative.StartsWith('../', [System.StringComparison]::Ordinal) -or
        $relative.Equals('.git', [System.StringComparison]::OrdinalIgnoreCase) -or
        $relative.StartsWith('.git/', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw ($FailurePrefix + '_FORBIDDEN')
    }
    return $relative
}

function Resolve-AwWriteAllowlist {
    param(
        [Parameter(Mandatory)][string]$Root,
        [AllowEmptyCollection()][string[]]$Paths = @()
    )
    if (@($Paths).Count -eq 0) { throw 'WRITE_ALLOWLIST_REQUIRED' }
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $result = [System.Collections.Generic.List[string]]::new()
    foreach ($path in @($Paths)) {
        $relative = ConvertTo-AwRepositoryRelativePath -Root $Root -Path ([string]$path) `
            -FailurePrefix 'WRITE_ALLOWLIST_PATH'
        Assert-AwPathHasNoReparsePoint -Root $Root -RelativePath $relative -FailureCode 'WRITE_ALLOWLIST_REPARSE_POINT_FORBIDDEN'
        $candidate = [System.IO.Path]::GetFullPath((Join-Path $Root $relative))
        if ([System.IO.Directory]::Exists($candidate)) {
            Assert-AwDirectoryTreeHasNoReparsePoint -Path $candidate -FailureCode 'WRITE_ALLOWLIST_REPARSE_POINT_FORBIDDEN'
            $relative = $relative.TrimEnd('/') + '/'
        }
        elseif ([System.IO.File]::Exists($candidate)) {
            Assert-AwFileHasSingleLink -Path $candidate -FailureCode 'WRITE_ALLOWLIST_HARDLINK_FORBIDDEN'
        }
        if ($seen.Add($relative)) { [void]$result.Add($relative) }
    }
    if ($result.Count -eq 0) { throw 'WRITE_ALLOWLIST_REQUIRED' }
    return @($result)
}

function Assert-AwPathHasNoReparsePoint {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)][string]$FailureCode
    )
    $current = [System.IO.Path]::GetFullPath($Root)
    foreach ($component in $RelativePath.Split([char]'/', [System.StringSplitOptions]::RemoveEmptyEntries)) {
        $current = [System.IO.Path]::GetFullPath((Join-Path $current $component))
        if (-not [System.IO.File]::Exists($current) -and -not [System.IO.Directory]::Exists($current)) { continue }
        try { $attributes = [System.IO.File]::GetAttributes($current) }
        catch { throw $FailureCode }
        if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw $FailureCode }
    }
}

function Assert-AwFileHasSingleLink {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$FailureCode
    )
    Initialize-AwJobType
    try { $count = [uint32][AwFileLinks]::GetLinkCount([System.IO.Path]::GetFullPath($Path)) }
    catch { throw $FailureCode }
    if ($count -ne 1) { throw $FailureCode }
}

function Assert-AwDirectoryTreeHasNoReparsePoint {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$FailureCode
    )
    $pending = [System.Collections.Generic.Stack[string]]::new()
    $pending.Push([System.IO.Path]::GetFullPath($Path))
    while ($pending.Count -gt 0) {
        $current = $pending.Pop()
        try { $entries = [System.IO.Directory]::EnumerateFileSystemEntries($current) }
        catch { throw $FailureCode }
        foreach ($entry in $entries) {
            try { $attributes = [System.IO.File]::GetAttributes($entry) }
            catch { throw $FailureCode }
            if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw $FailureCode }
            if (($attributes -band [System.IO.FileAttributes]::Directory) -ne 0) {
                $pending.Push([System.IO.Path]::GetFullPath($entry))
            }
            else { Assert-AwFileHasSingleLink -Path $entry -FailureCode 'WRITE_ALLOWLIST_HARDLINK_FORBIDDEN' }
        }
    }
}

function Resolve-AwReportedChangedPaths {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Paths
    )
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $result = [System.Collections.Generic.List[string]]::new()
    foreach ($path in @($Paths)) {
        $relative = ConvertTo-AwRepositoryRelativePath -Root $Root -Path ([string]$path) `
            -FailurePrefix 'GROK_CHANGED_PATH' -RequireRelative
        if (-not $seen.Add($relative)) { throw 'GROK_CHANGED_PATH_DUPLICATE' }
        [void]$result.Add($relative)
    }
    return @($result)
}

function Get-AwNulRecords {
    param([AllowEmptyString()][string]$Text = '')
    if ([string]::IsNullOrEmpty($Text)) { return @() }
    return @($Text.Split([char]0, [System.StringSplitOptions]::RemoveEmptyEntries))
}

function Get-AwFileSha256 {
    param([Parameter(Mandatory)][string]$Path)
    $stream = $null
    $sha = $null
    try {
        $share = [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
        $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, $share)
        $sha = [System.Security.Cryptography.SHA256]::Create()
        return [System.Convert]::ToHexString($sha.ComputeHash($stream))
    }
    catch { throw 'REPOSITORY_SNAPSHOT_FILE_READ_FAILED' }
    finally {
        if ($null -ne $sha) { $sha.Dispose() }
        if ($null -ne $stream) { $stream.Dispose() }
    }
}

function New-AwStringDictionary {
    [System.Collections.Generic.Dictionary[string,string]]::new([System.StringComparer]::OrdinalIgnoreCase)
}

function Start-AwRepositoryWatcher {
    param([Parameter(Mandatory)][string]$Root)
    Initialize-AwJobType
    $identity = Get-AwGitRepositoryIdentity -Root $Root
    $candidates = @($identity.TopLevel, $identity.GitDirectory, $identity.GitCommonDirectory) |
        ForEach-Object { [System.IO.Path]::GetFullPath([string]$_) } |
        Sort-Object { $_.Length }
    $roots = [System.Collections.Generic.List[string]]::new()
    foreach ($candidate in $candidates) {
        $covered = $false
        foreach ($existing in $roots) {
            $prefix = $existing.TrimEnd([char]'\', [char]'/') + [System.IO.Path]::DirectorySeparatorChar
            if ($candidate.Equals($existing, [System.StringComparison]::OrdinalIgnoreCase) -or
                $candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                $covered = $true
                break
            }
        }
        if (-not $covered) { [void]$roots.Add($candidate) }
    }
    try { return [AwRepositoryWatcher]::new([string[]]$roots.ToArray()) }
    catch { throw 'REPOSITORY_WATCHER_START_FAILED' }
}

function Stop-AwRepositoryWatcher {
    param([Parameter(Mandatory)][AwRepositoryWatcher]$Watcher)
    try {
        $paths = @($Watcher.StopAndGetPaths())
        $hasError = [bool]$Watcher.HasError
        $errorCount = [int]$Watcher.ErrorCount
        $errors = @($Watcher.GetErrors())
    }
    catch { throw 'REPOSITORY_WATCHER_STOP_FAILED' }
    finally { $Watcher.Dispose() }
    return [pscustomobject]@{
        Paths = $paths
        HasError = $hasError
        ErrorCount = $errorCount
        Errors = $errors
    }
}

function Get-AwRepositorySnapshotDigest {
    param([Parameter(Mandatory)]$Snapshot)
    $builder = [System.Text.StringBuilder]::new()
    foreach ($value in @(
        [string]$Snapshot.TopLevel, [string]$Snapshot.GitDirectory,
        [string]$Snapshot.GitCommonDirectory, [string]$Snapshot.Head, [string]$Snapshot.HeadRef
    )) {
        [void]$builder.Append($value.Length).Append(':').Append($value)
    }
    foreach ($map in @($Snapshot.IndexEntries, $Snapshot.WorktreeEntries)) {
        foreach ($key in @($map.Keys | Sort-Object)) {
            $value = [string]$map[$key]
            [void]$builder.Append($key.Length).Append(':').Append($key)
            [void]$builder.Append($value.Length).Append(':').Append($value)
        }
    }
    $bytes = (Get-AwUtf8).GetBytes($builder.ToString())
    return [System.Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData($bytes))
}

function Get-AwRepositorySnapshotOnce {
    param([Parameter(Mandatory)][string]$Root)
    $identity = Get-AwGitRepositoryIdentity -Root $Root
    if (-not $identity.TopLevel.Equals([System.IO.Path]::GetFullPath($Root), [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'REPOSITORY_SNAPSHOT_ROOT_CHANGED'
    }
    $head = (Invoke-AwGitReadOnly -Root $Root -FailureCode 'REPOSITORY_SNAPSHOT_HEAD_FAILED' `
        -Arguments @('rev-parse', '--verify', 'HEAD')).Trim()
    $headRef = (Invoke-AwGitReadOnly -Root $Root -FailureCode 'REPOSITORY_SNAPSHOT_HEAD_REF_FAILED' `
        -Arguments @('rev-parse', '--abbrev-ref', 'HEAD')).Trim()
    if ([string]::IsNullOrWhiteSpace($head) -or [string]::IsNullOrWhiteSpace($headRef)) {
        throw 'REPOSITORY_SNAPSHOT_HEAD_INVALID'
    }

    $indexEntries = New-AwStringDictionary
    $indexText = Invoke-AwGitReadOnly -Root $Root -FailureCode 'REPOSITORY_SNAPSHOT_INDEX_FAILED' `
        -Arguments @('ls-files', '--cached', '--stage', '-v', '-z')
    foreach ($record in @(Get-AwNulRecords -Text $indexText)) {
        $tab = $record.IndexOf("`t", [System.StringComparison]::Ordinal)
        if ($tab -lt 1 -or $tab -ge ($record.Length - 1)) { throw 'REPOSITORY_SNAPSHOT_INDEX_INVALID' }
        $metadata = $record.Substring(0, $tab)
        $relative = ConvertTo-AwRepositoryRelativePath -Root $Root -Path $record.Substring($tab + 1) `
            -FailurePrefix 'REPOSITORY_SNAPSHOT_INDEX_PATH' -RequireRelative
        if ($indexEntries.ContainsKey($relative)) {
            $indexEntries[$relative] = $indexEntries[$relative] + [char]0 + $metadata
        }
        else { $indexEntries[$relative] = $metadata }
    }

    $worktreeEntries = New-AwStringDictionary
    $pathText = Invoke-AwGitReadOnly -Root $Root -FailureCode 'REPOSITORY_SNAPSHOT_PATHS_FAILED' `
        -Arguments @('ls-files', '--cached', '--others', '--exclude-standard', '-z')
    $snapshotPaths = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($pathRecord in @(Get-AwNulRecords -Text $pathText)) {
        if (-not $snapshotPaths.Add([string]$pathRecord)) { continue }
        $relative = ConvertTo-AwRepositoryRelativePath -Root $Root -Path $pathRecord `
            -FailurePrefix 'REPOSITORY_SNAPSHOT_WORKTREE_PATH' -RequireRelative
        $full = [System.IO.Path]::GetFullPath((Join-Path $Root $relative))
        if ([System.IO.File]::Exists($full)) {
            $attributes = [System.IO.File]::GetAttributes($full)
            if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                $target = [string]([System.IO.FileInfo]::new($full).LinkTarget)
                $worktreeEntries[$relative] = 'LINK:' + $target
            }
            else { $worktreeEntries[$relative] = 'FILE:' + (Get-AwFileSha256 -Path $full) }
        }
        elseif ([System.IO.Directory]::Exists($full)) { $worktreeEntries[$relative] = 'DIRECTORY' }
        else { $worktreeEntries[$relative] = 'MISSING' }
    }
    $snapshot = [pscustomobject]@{
        TopLevel = [string]$identity.TopLevel
        GitDirectory = [string]$identity.GitDirectory
        GitCommonDirectory = [string]$identity.GitCommonDirectory
        Head = $head
        HeadRef = $headRef
        IndexEntries = $indexEntries
        WorktreeEntries = $worktreeEntries
        Digest = ''
    }
    $snapshot.Digest = Get-AwRepositorySnapshotDigest -Snapshot $snapshot
    return $snapshot
}

function Get-AwStableRepositorySnapshot {
    param([Parameter(Mandatory)][string]$Root)
    $first = Get-AwRepositorySnapshotOnce -Root $Root
    $second = Get-AwRepositorySnapshotOnce -Root $Root
    if ($first.Digest -cne $second.Digest) { throw 'REPOSITORY_SNAPSHOT_UNSTABLE' }
    return $second
}

function Get-AwChangedMapKeys {
    param([Parameter(Mandatory)]$Before, [Parameter(Mandatory)]$After)
    $keys = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($key in $Before.Keys) { [void]$keys.Add([string]$key) }
    foreach ($key in $After.Keys) { [void]$keys.Add([string]$key) }
    $changed = [System.Collections.Generic.List[string]]::new()
    foreach ($key in $keys) {
        $beforePresent = $Before.ContainsKey($key)
        $afterPresent = $After.ContainsKey($key)
        if ($beforePresent -ne $afterPresent -or
            ($beforePresent -and ([string]$Before[$key] -cne [string]$After[$key]))) {
            [void]$changed.Add($key)
        }
    }
    return @($changed | Sort-Object)
}

function Compare-AwRepositorySnapshots {
    param([Parameter(Mandatory)]$Before, [Parameter(Mandatory)]$After)
    $topologyChanged = (
        [string]$Before.TopLevel -cne [string]$After.TopLevel -or
        [string]$Before.GitDirectory -cne [string]$After.GitDirectory -or
        [string]$Before.GitCommonDirectory -cne [string]$After.GitCommonDirectory
    )
    $indexPaths = @(Get-AwChangedMapKeys -Before $Before.IndexEntries -After $After.IndexEntries)
    $worktreePaths = @(Get-AwChangedMapKeys -Before $Before.WorktreeEntries -After $After.WorktreeEntries)
    $all = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($path in @($indexPaths + $worktreePaths)) { [void]$all.Add([string]$path) }
    return [pscustomobject]@{
        TopologyChanged = $topologyChanged
        HeadChanged = ([string]$Before.Head -cne [string]$After.Head)
        HeadRefChanged = ([string]$Before.HeadRef -cne [string]$After.HeadRef)
        IndexPaths = $indexPaths
        WorktreePaths = $worktreePaths
        Paths = @($all | Sort-Object)
    }
}

function Assert-AwReadOnlyRepositoryUnchanged {
    param(
        [Parameter(Mandatory)]$Before,
        [Parameter(Mandatory)]$After,
        [Parameter(Mandatory)][ValidateSet('CODEX', 'GROK', 'OPUS')][string]$Provider,
        [Parameter(Mandatory)]$WatcherResult
    )
    $delta = Compare-AwRepositorySnapshots -Before $Before -After $After
    $watcherPaths = @($WatcherResult.Paths | Sort-Object)
    $snapshotPaths = @($delta.Paths | Sort-Object)
    $hasConcreteMutation = (
        $watcherPaths.Count -ne 0 -or $delta.TopologyChanged -or $delta.HeadChanged -or
        $delta.HeadRefChanged -or $snapshotPaths.Count -ne 0
    )
    if ($hasConcreteMutation -or [bool]$WatcherResult.HasError) {
        $watcherErrors = @()
        if ($null -ne $WatcherResult.PSObject.Properties['Errors']) {
            $watcherErrors = @($WatcherResult.Errors)
        }
        [Console]::Error.WriteLine((
            'REPOSITORY_GUARD provider={0} watcher_paths={1} snapshot_paths={2} watcher_errors={3} topology={4} head={5} head_ref={6}' -f
            $Provider, $watcherPaths.Count, $snapshotPaths.Count, $watcherErrors.Count,
            [bool]$delta.TopologyChanged, [bool]$delta.HeadChanged, [bool]$delta.HeadRefChanged
        ))
        if ($watcherPaths.Count -ne 0) {
            [Console]::Error.WriteLine('REPOSITORY_GUARD_WATCHER_PATHS=' +
                (ConvertTo-Json -InputObject ([string[]]@($watcherPaths | Select-Object -First 50)) -Compress))
        }
        if ($snapshotPaths.Count -ne 0) {
            [Console]::Error.WriteLine('REPOSITORY_GUARD_SNAPSHOT_PATHS=' +
                (ConvertTo-Json -InputObject ([string[]]@($snapshotPaths | Select-Object -First 50)) -Compress))
        }
        if ($watcherErrors.Count -ne 0) {
            [Console]::Error.WriteLine('REPOSITORY_GUARD_WATCHER_ERRORS=' +
                (ConvertTo-Json -InputObject ([string[]]@($watcherErrors | Select-Object -First 20)) -Compress))
        }
    }
    if ($hasConcreteMutation) {
        throw ($Provider + '_READ_ONLY_REPOSITORY_MUTATED')
    }
    if ([bool]$WatcherResult.HasError) { throw ($Provider + '_REPOSITORY_WATCHER_UNRELIABLE') }
}

function Test-AwPathWithinAllowlist {
    param(
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Allowlist
    )
    foreach ($entry in @($Allowlist)) {
        $normalized = $entry.TrimEnd('/')
        if ($RelativePath.Equals($normalized, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
        if ($entry.EndsWith('/', [System.StringComparison]::Ordinal) -and
            $RelativePath.StartsWith($entry, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Assert-AwGrokMutationScope {
    param(
        [Parameter(Mandatory)]$Delta,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Allowlist,
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)]$WatcherResult
    )
    if ([bool]$WatcherResult.HasError) { throw 'GROK_REPOSITORY_WATCHER_OVERFLOW' }
    if ($Delta.TopologyChanged -or $Delta.HeadChanged -or $Delta.HeadRefChanged) {
        throw 'GROK_GIT_STATE_MUTATED'
    }
    if (@($Delta.IndexPaths).Count -ne 0) { throw 'GROK_GIT_INDEX_MUTATED' }
    foreach ($actual in @($Delta.Paths)) {
        Assert-AwPathHasNoReparsePoint -Root $Root -RelativePath $actual -FailureCode 'GROK_CHANGE_REPARSE_POINT_FORBIDDEN'
        $actualFull = [System.IO.Path]::GetFullPath((Join-Path $Root $actual))
        if ([System.IO.File]::Exists($actualFull)) {
            Assert-AwFileHasSingleLink -Path $actualFull -FailureCode 'GROK_CHANGE_HARDLINK_FORBIDDEN'
        }
        if (-not (Test-AwPathWithinAllowlist -RelativePath $actual -Allowlist $Allowlist)) {
            throw 'GROK_CHANGE_OUTSIDE_ALLOWLIST'
        }
    }
    $actualSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($path in @($Delta.Paths)) { [void]$actualSet.Add([string]$path) }
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd([char]'\', [char]'/')
    $rootPrefix = $rootFull + [System.IO.Path]::DirectorySeparatorChar
    foreach ($watchPath in @($WatcherResult.Paths)) {
        try { $full = [System.IO.Path]::GetFullPath([string]$watchPath) }
        catch { throw 'GROK_REPOSITORY_WATCHER_PATH_INVALID' }
        if (-not $full.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'GROK_GIT_STATE_MUTATED'
        }
        $relative = [System.IO.Path]::GetRelativePath($rootFull, $full).Replace('\', '/')
        if ($relative.Equals('.git', [System.StringComparison]::OrdinalIgnoreCase) -or
            $relative.StartsWith('.git/', [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'GROK_GIT_STATE_MUTATED'
        }
        $represented = $actualSet.Contains($relative)
        if (-not $represented) {
            if ($relative -eq '.' -and $actualSet.Count -ne 0) { $represented = $true }
            else {
                foreach ($actualPath in $actualSet) {
                    if ($actualPath.StartsWith($relative.TrimEnd('/') + '/', [System.StringComparison]::OrdinalIgnoreCase)) {
                        $represented = $true
                        break
                    }
                }
            }
        }
        if (-not $represented) {
            if (-not (Test-AwPathWithinAllowlist -RelativePath $relative -Allowlist $Allowlist)) {
                throw 'GROK_CHANGE_OUTSIDE_ALLOWLIST'
            }
            throw 'GROK_WATCHER_CHANGE_NOT_IN_FINGERPRINT'
        }
    }
}

function Assert-AwPathSetsEqual {
    param(
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Expected,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Actual,
        [Parameter(Mandatory)][string]$FailureCode
    )
    $expectedSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $actualSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($path in @($Expected)) { [void]$expectedSet.Add([string]$path) }
    foreach ($path in @($Actual)) { [void]$actualSet.Add([string]$path) }
    if (-not $expectedSet.SetEquals($actualSet)) { throw $FailureCode }
}

function Test-AwGrokCredentialMaterial {
    param([Parameter(Mandatory)][hashtable]$Environment)

    if (-not [string]::IsNullOrWhiteSpace([string]$Environment['XAI_API_KEY'])) { return $true }
    $grokHome = [string]$Environment['GROK_HOME']
    if ([string]::IsNullOrWhiteSpace($grokHome)) {
        $userHome = [string]$Environment['HOME']
        if ([string]::IsNullOrWhiteSpace($userHome)) { $userHome = [string]$Environment['USERPROFILE'] }
        if ([string]::IsNullOrWhiteSpace($userHome)) { return $false }
        $grokHome = Join-Path $userHome '.grok'
    }
    try { $authPath = [System.IO.Path]::GetFullPath((Join-Path $grokHome 'auth.json')) }
    catch { return $false }
    if (-not [System.IO.File]::Exists($authPath)) { return $false }

    try {
        $authText = [System.IO.File]::ReadAllText($authPath, (Get-AwUtf8))
        $auth = $authText | ConvertFrom-Json -Depth 20 -ErrorAction Stop
    }
    catch { return $false }
    if ($null -eq $auth -or $auth -is [array] -or $auth -is [string]) { return $false }

    foreach ($property in $auth.PSObject.Properties) {
        $credential = $property.Value
        if ($null -eq $credential -or $credential -is [array] -or $credential -is [string]) { continue }
        $hasRefresh = $false
        $refreshProperty = $credential.PSObject.Properties['refresh_token']
        if ($null -ne $refreshProperty) {
            $hasRefresh = -not [string]::IsNullOrWhiteSpace([string]$refreshProperty.Value)
        }
        if ($hasRefresh) { return $true }

        $hasAccess = $false
        foreach ($name in @('key', 'access_token', 'api_key')) {
            $candidate = $credential.PSObject.Properties[$name]
            if ($null -ne $candidate -and -not [string]::IsNullOrWhiteSpace([string]$candidate.Value)) {
                $hasAccess = $true
                break
            }
        }
        if (-not $hasAccess) { continue }

        $expiryProperty = $credential.PSObject.Properties['expires_at']
        if ($null -eq $expiryProperty -or [string]::IsNullOrWhiteSpace([string]$expiryProperty.Value)) { return $true }
        try { $expiry = [System.DateTimeOffset]::Parse([string]$expiryProperty.Value, [Globalization.CultureInfo]::InvariantCulture) }
        catch { continue }
        if ($expiry -gt [System.DateTimeOffset]::UtcNow) { return $true }
    }
    return $false
}

function Assert-AwProviderAuthentication {
    param(
        [Parameter(Mandatory)][ValidateSet('Grok', 'Opus', 'Codex')][string]$Provider,
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][hashtable]$Environment,
        [Parameter(Mandatory)][ValidateRange(1, 300)][int]$TimeoutSeconds
    )

    $providerUpper = $Provider.ToUpperInvariant()
    if ($Provider -eq 'Grok') {
        if (-not (Test-AwGrokCredentialMaterial -Environment $Environment)) {
            throw ('AUTH_PREFLIGHT_FAILED_' + $providerUpper)
        }
        return
    }

    $arguments = if ($Provider -eq 'Opus') { @('auth', 'status', '--json') } else { @('login', 'status') }
    try {
        $result = Invoke-AwNativeOnce -Executable $Executable -Arguments $arguments `
            -WorkingDirectory $WorkingDirectory -TimeoutSeconds $TimeoutSeconds `
            -MaxOutputBytes 65536 -Environment $Environment
    }
    catch {
        if ([string]$_.Exception.Message -eq 'AI_PROCESS_KILL_UNVERIFIED') { throw }
        throw ('AUTH_PREFLIGHT_FAILED_' + $providerUpper)
    }
    if ([int]$result.ExitCode -ne 0) { throw ('AUTH_PREFLIGHT_FAILED_' + $providerUpper) }
}

function Assert-AwProviderAuthenticationReadOnly {
    param(
        [Parameter(Mandatory)][ValidateSet('Grok', 'Opus', 'Codex')][string]$Provider,
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][hashtable]$Environment,
        [Parameter(Mandatory)][ValidateRange(1, 300)][int]$TimeoutSeconds
    )

    $providerUpper = $Provider.ToUpperInvariant()
    $before = Get-AwStableRepositorySnapshot -Root $WorkingDirectory
    $watcher = Start-AwRepositoryWatcher -Root $WorkingDirectory
    $authenticationFailure = $null
    $guardFailure = $null
    $watcherResult = $null
    $after = $null
    try {
        try {
            Assert-AwProviderAuthentication -Provider $Provider -Executable $Executable `
                -WorkingDirectory $WorkingDirectory -Environment $Environment `
                -TimeoutSeconds $TimeoutSeconds
        }
        catch { $authenticationFailure = $_ }
    }
    finally {
        try { $watcherResult = Stop-AwRepositoryWatcher -Watcher $watcher }
        catch { $guardFailure = $_ }
        if ($null -eq $guardFailure) {
            try { $after = Get-AwStableRepositorySnapshot -Root $WorkingDirectory }
            catch { $guardFailure = $_ }
        }
        if ($null -eq $guardFailure) {
            try {
                Assert-AwReadOnlyRepositoryUnchanged -Before $before -After $after `
                    -Provider $providerUpper -WatcherResult $watcherResult
            }
            catch { $guardFailure = $_ }
        }
        if ($null -ne $guardFailure) { throw $guardFailure }
    }
    if ($null -ne $authenticationFailure) { throw $authenticationFailure }
    return $after
}

function Stop-AwProcessTree {
    param(
        [Parameter(Mandatory)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory)][AwJobHandle]$Job
    )
    $jobStopped = $false
    try { $jobStopped = $Job.TerminateAndWait(10000) } catch { $jobStopped = $false }
    if (-not $Process.HasExited) {
        try { $Process.Kill($true) } catch { }
        try { [void]$Process.WaitForExit(10000) } catch { }
    }
    return ($jobStopped -and $Process.HasExited)
}

function Invoke-AwNativeOnce {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Arguments,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [AllowEmptyString()][string]$StdinText = '',
        [Parameter(Mandatory)][ValidateRange(1, 86400)][int]$TimeoutSeconds,
        [Parameter(Mandatory)][ValidateRange(65536, 67108864)][int64]$MaxOutputBytes,
        [hashtable]$Environment = @{}
    )

    if (-not [System.IO.Path]::IsPathFullyQualified($Executable) -or
        -not $Executable.EndsWith('.exe', [System.StringComparison]::OrdinalIgnoreCase) -or
        -not [System.IO.File]::Exists($Executable)) { throw 'NATIVE_EXECUTABLE_REQUIRED' }
    if (-not [System.IO.Directory]::Exists($WorkingDirectory)) { throw 'WORKING_DIRECTORY_MISSING' }

    Initialize-AwJobType
    $utf8 = Get-AwUtf8
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Executable
    foreach ($argument in $Arguments) { [void]$start.ArgumentList.Add([string]$argument) }
    $start.WorkingDirectory = $WorkingDirectory
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardInputEncoding = $utf8
    $start.StandardOutputEncoding = $utf8
    $start.StandardErrorEncoding = $utf8
    $start.Environment.Clear()
    foreach ($key in $Environment.Keys) {
        $value = $Environment[$key]
        if ($null -eq $value) { [void]$start.Environment.Remove([string]$key) }
        else { $start.Environment[[string]$key] = [string]$value }
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    $job = [AwJobHandle]::new()
    $started = $false
    $timedOut = $false
    $outputLimit = $false
    $stdoutMemory = [System.IO.MemoryStream]::new()
    $stderrMemory = [System.IO.MemoryStream]::new()
    $stdoutBuffer = [byte[]]::new(8192)
    $stderrBuffer = [byte[]]::new(8192)
    try {
        try { $started = $process.Start() }
        catch { throw 'AI_PROCESS_START_FAILED' }
        if (-not $started) { throw 'AI_PROCESS_START_FAILED' }

        $clock = [System.Diagnostics.Stopwatch]::StartNew()
        try { $job.Assign($process) }
        catch {
            try { $process.Kill($true) } catch { }
            throw 'AI_PROCESS_JOB_ASSIGN_FAILED'
        }
        $stdoutTask = $process.StandardOutput.BaseStream.ReadAsync($stdoutBuffer, 0, $stdoutBuffer.Length)
        $stderrTask = $process.StandardError.BaseStream.ReadAsync($stderrBuffer, 0, $stderrBuffer.Length)
        $stdoutClosed = $false
        $stderrClosed = $false
        $stdinClosed = $false
        $stdinBytes = $utf8.GetBytes($StdinText)
        $stdinTask = if ($stdinBytes.Length -gt 0) {
            $process.StandardInput.BaseStream.WriteAsync($stdinBytes, 0, $stdinBytes.Length)
        }
        else { $null }
        if ($null -eq $stdinTask) { $process.StandardInput.Close(); $stdinClosed = $true }

        while ($true) {
            if (-not $stdinClosed -and $stdinTask.IsCompleted) {
                try { [void]$stdinTask.GetAwaiter().GetResult() }
                catch { if (-not $process.HasExited) { throw 'AI_STDIN_WRITE_FAILED' } }
                try { $process.StandardInput.Close() } catch { }
                $stdinClosed = $true
            }

            if (-not $stdoutClosed -and $stdoutTask.IsCompleted) {
                try { $count = [int]$stdoutTask.GetAwaiter().GetResult() } catch { throw 'AI_STDOUT_READ_FAILED' }
                if ($count -eq 0) { $stdoutClosed = $true }
                else {
                    if (($stdoutMemory.Length + $stderrMemory.Length + $count) -gt $MaxOutputBytes) { $outputLimit = $true; break }
                    $stdoutMemory.Write($stdoutBuffer, 0, $count)
                    $stdoutTask = $process.StandardOutput.BaseStream.ReadAsync($stdoutBuffer, 0, $stdoutBuffer.Length)
                }
            }

            if (-not $stderrClosed -and $stderrTask.IsCompleted) {
                try { $count = [int]$stderrTask.GetAwaiter().GetResult() } catch { throw 'AI_STDERR_READ_FAILED' }
                if ($count -eq 0) { $stderrClosed = $true }
                else {
                    if (($stdoutMemory.Length + $stderrMemory.Length + $count) -gt $MaxOutputBytes) { $outputLimit = $true; break }
                    $stderrMemory.Write($stderrBuffer, 0, $count)
                    $stderrTask = $process.StandardError.BaseStream.ReadAsync($stderrBuffer, 0, $stderrBuffer.Length)
                }
            }

            if ($process.HasExited -and $stdoutClosed -and $stderrClosed) { break }
            if ($clock.Elapsed.TotalSeconds -ge $TimeoutSeconds) { $timedOut = $true; break }
            Start-Sleep -Milliseconds 10
        }

        if ($timedOut -or $outputLimit) {
            $killed = Stop-AwProcessTree -Process $process -Job $job
            if (-not $killed) { throw 'AI_PROCESS_KILL_UNVERIFIED' }
        }
        elseif (-not $process.HasExited) {
            throw 'AI_PROCESS_EXIT_UNVERIFIED'
        }
        elseif (-not $job.IsEmpty()) {
            $killed = Stop-AwProcessTree -Process $process -Job $job
            if (-not $killed) { throw 'AI_PROCESS_KILL_UNVERIFIED' }
        }

        $decoder = if ($timedOut -or $outputLimit) { [System.Text.UTF8Encoding]::new($false, $false) } else { $utf8 }
        $stdout = $decoder.GetString($stdoutMemory.GetBuffer(), 0, [int]$stdoutMemory.Length)
        $stderr = $decoder.GetString($stderrMemory.GetBuffer(), 0, [int]$stderrMemory.Length)
        $exitCode = if ($timedOut) { 124 } elseif ($outputLimit) { 125 } else { [int]$process.ExitCode }
        return [pscustomobject]@{
            ExitCode = $exitCode
            ChildExitCode = if ($process.HasExited) { [int]$process.ExitCode } else { -1 }
            StdOut = $stdout
            StdErr = $stderr
            TimedOut = $timedOut
            OutputLimitExceeded = $outputLimit
        }
    }
    catch {
        $failure = $_
        if ($started) {
            $stopped = Stop-AwProcessTree -Process $process -Job $job
            if (-not $stopped) { throw 'AI_PROCESS_KILL_UNVERIFIED' }
        }
        throw $failure
    }
    finally {
        if ($started) {
            try {
                if (-not $process.HasExited -or -not $job.IsEmpty()) { [void](Stop-AwProcessTree -Process $process -Job $job) }
            }
            catch { }
        }
        $job.Dispose()
        $stdoutMemory.Dispose()
        $stderrMemory.Dispose()
        $process.Dispose()
    }
}

function Write-AwChildOutput {
    param([Parameter(Mandatory)]$Result)
    if (-not [string]::IsNullOrEmpty([string]$Result.StdOut)) { [Console]::Out.Write([string]$Result.StdOut) }
    if (-not [string]::IsNullOrEmpty([string]$Result.StdErr)) { [Console]::Error.Write([string]$Result.StdErr) }
}

function Write-AwAuthGuidance {
    param([Parameter(Mandatory)][string]$Message)
    switch -Regex ($Message) {
        '^AUTH_PREFLIGHT_FAILED_GROK$' { [Console]::Error.WriteLine('AUTH_GUIDANCE=grok login or set XAI_API_KEY'); break }
        '^AUTH_PREFLIGHT_FAILED_OPUS$' { [Console]::Error.WriteLine('AUTH_GUIDANCE=claude auth login'); break }
        '^AUTH_PREFLIGHT_FAILED_CODEX$' { [Console]::Error.WriteLine('AUTH_GUIDANCE=codex login'); break }
    }
}

function Get-AwWrapperErrorExitCode {
    param([Parameter(Mandatory)][string]$Message)
    if ($Message -eq 'AI_PROCESS_KILL_UNVERIFIED') { return 126 }
    if ($Message -match '^AUTH_PREFLIGHT_FAILED_') { return 65 }
    if ($Message -match '^(CODEX|GROK|OPUS)_READ_ONLY_REPOSITORY_MUTATED$') { return 20 }
    if ($Message -match '^(CODEX|GROK|OPUS)_REPOSITORY_WATCHER_UNRELIABLE$') { return 70 }
    if ($Message -match '^GROK_(CHANGE|GIT|MUTATION|REPORTED|CHANGED|WATCHER|REPOSITORY_WATCHER)') { return 20 }
    if ($Message -match '^(CONFIG_|CODEX_GRADE_|CODEX_REVIEW_|REPOSITORY_ROOT_|PROMPT_|WRITE_ALLOWLIST_|NATIVE_EXECUTABLE_REQUIRED|WORKING_DIRECTORY_MISSING)') { return 64 }
    return 70
}
