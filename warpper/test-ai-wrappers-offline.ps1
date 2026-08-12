#requires -Version 7.0
[CmdletBinding()]
param([string]$CasePattern = '*')

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$script:Passed = 0
$script:Failed = 0
$script:Failures = [System.Collections.Generic.List[string]]::new()
$script:Utf8 = [System.Text.UTF8Encoding]::new($false, $true)
$script:PackageRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$script:Pwsh = [System.IO.Path]::GetFullPath((Get-Process -Id $PID).Path)
$tempBase = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Temp'))
[void][System.IO.Directory]::CreateDirectory($tempBase)
$script:TestRoot = Join-Path $tempBase ('ai-wrapper-offline-' + [guid]::NewGuid().ToString('N'))
$script:RuntimePackage = Join-Path $script:TestRoot 'runtime package'
$script:Repository = Join-Path $script:TestRoot 'C 또는 USB 작업 폴더 (검증)'
$script:AlternateRepository = Join-Path $script:TestRoot 'GitHub local clone & 100% (override)'
$script:NonGitDirectory = Join-Path $script:TestRoot 'existing but not git'
$script:FakeGitDirectory = Join-Path $script:TestRoot 'fake git marker'
$script:RepositorySubdirectory = Join-Path $script:Repository 'backend'
$script:GrokAuthHome = Join-Path $script:TestRoot 'fake-grok-home'
$script:LogPath = Join-Path $script:TestRoot 'fake-calls.jsonl'
$script:TaskScenarioPath = Join-Path $script:TestRoot 'fake-task-scenario.txt'
$script:AuthScenarioPath = Join-Path $script:TestRoot 'fake-auth-scenario.txt'
$script:ConfigPath = Join-Path $script:RuntimePackage 'wrapper-config.json'
$script:ChildPidPath = Join-Path $script:TestRoot 'descendant.pid'
$script:DirtyWipPath = Join-Path $script:Repository 'dirty-wip.txt'
$script:IgnoredPath = Join-Path $script:Repository 'ignored-output.tmp'
$script:OutsideReparseTarget = Join-Path $script:TestRoot 'outside-reparse-target'
$script:ReparseAllowDirectory = Join-Path $script:Repository 'allowed-tree'
$script:ReparseDescendant = Join-Path $script:ReparseAllowDirectory 'outside-link'
$script:HardlinkAllowDirectory = Join-Path $script:Repository 'hardlink-tree'
$script:OutsideHardlinkTarget = Join-Path $script:TestRoot 'outside-hardlink-target.txt'
$script:HardlinkDescendant = Join-Path $script:HardlinkAllowDirectory 'outside-hardlink.txt'
try { $script:Git = [System.IO.Path]::GetFullPath(@(Get-Command git.exe -CommandType Application -ErrorAction Stop)[0].Source) }
catch { throw 'GIT_EXECUTABLE_MISSING_FOR_TEST' }

function Assert-Aw {
    param([Parameter(Mandatory)][bool]$Condition, [Parameter(Mandatory)][string]$Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-AwGitSetup {
    param(
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    $output = & $script:Git -C $WorkingDirectory @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw ('GIT_SETUP_FAILED_' + ($output -join '_')) }
    return @($output)
}

function Test-AwArgumentPair {
    param([object[]]$Arguments, [string]$Name, [string]$Value)
    for ($index = 0; $index -lt ($Arguments.Count - 1); $index++) {
        if ([string]$Arguments[$index] -eq $Name -and [string]$Arguments[$index + 1] -eq $Value) { return $true }
    }
    return $false
}

function Get-AwArgumentValue {
    param([object[]]$Arguments, [string]$Name)
    for ($index = 0; $index -lt ($Arguments.Count - 1); $index++) {
        if ([string]$Arguments[$index] -eq $Name) { return [string]$Arguments[$index + 1] }
    }
    throw ('ARGUMENT_NOT_FOUND:' + $Name)
}

function Get-AwCallCount {
    if (-not [System.IO.File]::Exists($script:LogPath)) { return 0 }
    return @([System.IO.File]::ReadAllLines($script:LogPath, $script:Utf8)).Count
}

function Read-AwCalls {
    if (-not [System.IO.File]::Exists($script:LogPath)) { return @() }
    return @([System.IO.File]::ReadAllLines($script:LogPath, $script:Utf8) | ForEach-Object {
        $_ | ConvertFrom-Json -Depth 30 -ErrorAction Stop
    })
}

function Get-AwTaskCallCount {
    return @(Read-AwCalls | Where-Object { [string]$_.kind -eq 'task' }).Count
}

function Get-AwPreflightCallCount {
    return @(Read-AwCalls | Where-Object { [string]$_.kind -eq 'auth_preflight' }).Count
}

function Read-AwLastCall {
    $lines = [System.IO.File]::ReadAllLines($script:LogPath, $script:Utf8)
    return ($lines[$lines.Length - 1] | ConvertFrom-Json -Depth 30 -ErrorAction Stop)
}

function Read-AwLastTaskCall {
    $calls = @(Read-AwCalls | Where-Object { [string]$_.kind -eq 'task' })
    if ($calls.Count -eq 0) { throw 'NO_TASK_CALL' }
    return $calls[$calls.Count - 1]
}

function Read-AwLastPreflightCall {
    $calls = @(Read-AwCalls | Where-Object { [string]$_.kind -eq 'auth_preflight' })
    if ($calls.Count -eq 0) { throw 'NO_PREFLIGHT_CALL' }
    return $calls[$calls.Count - 1]
}

function Invoke-AwWrapperProcess {
    param(
        [Parameter(Mandatory)][string]$ScriptName,
        [Parameter(Mandatory)][string]$Scenario,
        [string]$AuthScenario = 'auth_ok',
        [string[]]$ExtraArguments = @(),
        [string]$PromptText = '오프라인 계약 검증 task & 100%',
        [string]$PromptFilePath = '',
        [string]$RepositoryRoot = $script:Repository,
        [switch]$NoRepositoryOverride,
        [switch]$NoDefaultWriteAllowlist,
        [AllowEmptyString()][string]$XaiApiKey = 'XAI_CANARY',
        [AllowEmptyString()][string]$GrokHome = 'GROK_HOME_CANARY',
        [switch]$NoDefaultCodexGrade,
        [int]$OuterTimeoutMilliseconds = 20000
    )
    [System.IO.File]::WriteAllText($script:TaskScenarioPath, $Scenario, $script:Utf8)
    [System.IO.File]::WriteAllText($script:AuthScenarioPath, $AuthScenario, $script:Utf8)
    if ([System.IO.File]::Exists($script:DirtyWipPath)) {
        [System.IO.File]::WriteAllText($script:DirtyWipPath, 'existing dirty WIP', $script:Utf8)
    }
    if ([System.IO.Directory]::Exists($RepositoryRoot)) {
        foreach ($relative in @(
            'src\grok-fake.txt', 'src\forbidden.txt', 'src\reported-only.txt',
            'src\codex-mutated.txt', 'src\opus-mutated.txt', 'src\auth-mutated.txt', 'ignored-output.tmp'
        )) {
            $generated = Join-Path $RepositoryRoot $relative
            if ([System.IO.File]::Exists($generated)) { [System.IO.File]::Delete($generated) }
        }
        foreach ($relativeDirectory in @('scratch-empty', 'delete-tree')) {
            $generatedDirectory = Join-Path $RepositoryRoot $relativeDirectory
            if ([System.IO.Directory]::Exists($generatedDirectory)) {
                [System.IO.Directory]::Delete($generatedDirectory, $true)
            }
        }
        $scopeFile = Join-Path $RepositoryRoot 'scope-file.txt'
        if ([System.IO.Directory]::Exists($scopeFile)) { [System.IO.Directory]::Delete($scopeFile, $true) }
        [System.IO.File]::WriteAllText($scopeFile, 'scope file baseline', $script:Utf8)
        if ($Scenario -eq 'grok_delete_parent') {
            $deleteTree = Join-Path $RepositoryRoot 'delete-tree'
            [void][System.IO.Directory]::CreateDirectory($deleteTree)
            [System.IO.File]::WriteAllText((Join-Path $deleteTree 'child.txt'), 'delete baseline', $script:Utf8)
        }
    }
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $script:Pwsh
    $promptArguments = if ([string]::IsNullOrWhiteSpace($PromptFilePath)) {
        @('-Prompt', $PromptText)
    }
    else { @('-PromptFile', $PromptFilePath) }
    $repositoryArguments = if ($NoRepositoryOverride) { @() } else { @('-RepositoryRoot', $RepositoryRoot) }
    $hasExplicitAllowlist = @($ExtraArguments | Where-Object { $_ -in @('-WriteAllowPath', '-AllowPath') }).Count -ne 0
    $allowlistArguments = if ($ScriptName -eq 'invoke-grok.ps1' -and -not $NoDefaultWriteAllowlist -and -not $hasExplicitAllowlist) {
        @('-WriteAllowPath', 'src/grok-fake.txt')
    }
    else { @() }
    $hasCodexGrade = @($ExtraArguments | Where-Object {
        $_ -in @('-SimpleTest', '-TestGrade', '-ReviewGrade')
    }).Count -ne 0
    $codexSessionArguments = if ($ScriptName -eq 'invoke-codex.ps1' -and -not $hasCodexGrade -and -not $NoDefaultCodexGrade) {
        @('-ReviewGrade', '3')
    }
    else { @() }
    foreach ($item in @(
        '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', (Join-Path $script:RuntimePackage $ScriptName)
    ) + $repositoryArguments + $promptArguments + $allowlistArguments + $codexSessionArguments + $ExtraArguments) { [void]$start.ArgumentList.Add([string]$item) }
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.Environment['OPENAI_API_KEY'] = 'OPENAI_CANARY'
    $start.Environment['ANTHROPIC_API_KEY'] = 'ANTHROPIC_CANARY'
    $start.Environment['XAI_API_KEY'] = $XaiApiKey
    $start.Environment['GROK_API_KEY'] = 'GROK_CANARY'
    $start.Environment['GROK_SUBAGENTS'] = '0'
    $start.Environment['UNRELATED_CLIENT_SECRET'] = 'UNRELATED_CANARY'
    $start.Environment['GH_TOKEN'] = 'GITHUB_CANARY'
    $start.Environment['AWS_ACCESS_KEY_ID'] = 'AWS_CANARY'
    $start.Environment['DATABASE_URL'] = 'DATABASE_CANARY'
    $start.Environment['GITHUB_PAT'] = 'GITHUB_PAT_CANARY'
    $start.Environment['SLACK_WEBHOOK_URL'] = 'SLACK_CANARY'
    $start.Environment['CODEX_HOME'] = 'CODEX_HOME_CANARY'
    $start.Environment['CLAUDE_CONFIG_DIR'] = 'CLAUDE_HOME_CANARY'
    $start.Environment['GROK_HOME'] = $GrokHome
    $start.Environment['TEMP'] = 'C:\WINDOWS\TEMP'
    $start.Environment['TMP'] = 'C:\WINDOWS\TEMP'
    $start.Environment['PSModulePath'] = 'POISONED_PSMODULEPATH_CANARY'

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        Assert-Aw -Condition $process.Start() -Message 'WRAPPER_PROCESS_START_FAILED'
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($OuterTimeoutMilliseconds)) {
            try { $process.Kill($true) } catch { }
            throw 'WRAPPER_PROCESS_OUTER_TIMEOUT'
        }
        return [pscustomobject]@{
            ExitCode = [int]$process.ExitCode
            StdOut = [string]$stdoutTask.GetAwaiter().GetResult()
            StdErr = [string]$stderrTask.GetAwaiter().GetResult()
        }
    }
    finally { $process.Dispose() }
}

function Invoke-AwCp949ConsoleUtf8Probe {
    # The probe deliberately starts with a CP949 console and captures raw
    # redirected bytes. It never uses a StreamReader, so a successful strict
    # UTF-8 decode proves the core changed the actual console emit boundary.
    $probePath = Join-Path $script:RuntimePackage 'cp949-console-utf8-probe.ps1'
    $probeText = @'
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::GetEncoding(949)
[Console]::InputEncoding = [System.Text.Encoding]::GetEncoding(949)
. (Join-Path $PSScriptRoot 'ai-wrapper-core.ps1')
Write-AwChildOutput -Result ([pscustomobject]@{
    StdOut = '표준출력 한글'
    StdErr = '표준오류 한글'
})
'@
    [System.IO.File]::WriteAllText($probePath, $probeText, $script:Utf8)
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $script:Pwsh
    foreach ($item in @('-NoLogo', '-NoProfile', '-NonInteractive', '-File', $probePath)) {
        [void]$start.ArgumentList.Add([string]$item)
    }
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    $stdoutMemory = [System.IO.MemoryStream]::new()
    $stderrMemory = [System.IO.MemoryStream]::new()
    try {
        Assert-Aw -Condition $process.Start() -Message 'CP949_PROBE_START_FAILED'
        $stdoutTask = $process.StandardOutput.BaseStream.CopyToAsync($stdoutMemory)
        $stderrTask = $process.StandardError.BaseStream.CopyToAsync($stderrMemory)
        Assert-Aw -Condition $process.WaitForExit(20000) -Message 'CP949_PROBE_TIMEOUT'
        [void]$stdoutTask.GetAwaiter().GetResult()
        [void]$stderrTask.GetAwaiter().GetResult()
        Assert-Aw -Condition ($process.ExitCode -eq 0) -Message ('CP949_PROBE_EXIT_' + $process.ExitCode)
        $strictUtf8 = [System.Text.UTF8Encoding]::new($false, $true)
        try {
            $stdout = $strictUtf8.GetString($stdoutMemory.ToArray())
            $stderr = $strictUtf8.GetString($stderrMemory.ToArray())
        }
        catch {
            throw 'CP949_PARENT_EMIT_NOT_STRICT_UTF8'
        }
        return [pscustomobject]@{
            StdOut = $stdout
            StdErr = $stderr
            StdOutBytes = $stdoutMemory.ToArray()
            StdErrBytes = $stderrMemory.ToArray()
        }
    }
    finally {
        $stdoutMemory.Dispose()
        $stderrMemory.Dispose()
        $process.Dispose()
    }
}

function Invoke-AwCase {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][scriptblock]$Body)
    if ($Name -notlike $CasePattern) { return }
    try {
        & $Body
        $script:Passed++
        [Console]::Out.WriteLine('PASS ' + $Name)
    }
    catch {
        $script:Failed++
        $detail = $Name + ': ' + $_.Exception.Message
        [void]$script:Failures.Add($detail)
        [Console]::Out.WriteLine('FAIL ' + $detail)
    }
}

$fakeSource = @'
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;

public static class Program
{
    private static string ValueAfter(string[] args, string name)
    {
        for (int i = 0; i + 1 < args.Length; i++)
            if (args[i] == name) return args[i + 1];
        return "";
    }

    private static bool HasArgument(string[] args, string name)
    {
        for (int i = 0; i < args.Length; i++) if (args[i] == name) return true;
        return false;
    }

    private static string Json(string value)
    {
        if (value == null) return "null";
        StringBuilder result = new StringBuilder();
        result.Append('"');
        foreach (char character in value)
        {
            switch (character)
            {
                case '"': result.Append("\\\""); break;
                case '\\': result.Append("\\\\"); break;
                case '\b': result.Append("\\b"); break;
                case '\f': result.Append("\\f"); break;
                case '\n': result.Append("\\n"); break;
                case '\r': result.Append("\\r"); break;
                case '\t': result.Append("\\t"); break;
                default:
                    if (character < 32) result.Append("\\u" + ((int)character).ToString("x4"));
                    else result.Append(character);
                    break;
            }
        }
        result.Append('"');
        return result.ToString();
    }

    private static string JsonArray(string[] values)
    {
        StringBuilder result = new StringBuilder("[");
        for (int index = 0; index < values.Length; index++)
        {
            if (index > 0) result.Append(',');
            result.Append(Json(values[index]));
        }
        result.Append(']');
        return result.ToString();
    }

    private static void WriteLog(string logPath, string kind, string provider, string[] args, string stdin, string task, int pid)
    {
        string entry = "{" +
            "\"kind\":" + Json(kind) + "," +
            "\"provider\":" + Json(provider) + "," +
            "\"args\":" + JsonArray(args) + "," +
            "\"cwd\":" + Json(Environment.CurrentDirectory) + "," +
            "\"stdin\":" + Json(stdin) + "," +
            "\"task\":" + Json(task) + "," +
            "\"pid\":" + pid.ToString() + "," +
            "\"env\":{" +
                "\"openai\":" + Json(Environment.GetEnvironmentVariable("OPENAI_API_KEY")) + "," +
                "\"anthropic\":" + Json(Environment.GetEnvironmentVariable("ANTHROPIC_API_KEY")) + "," +
                "\"xai\":" + Json(Environment.GetEnvironmentVariable("XAI_API_KEY")) + "," +
                "\"grok\":" + Json(Environment.GetEnvironmentVariable("GROK_API_KEY")) + "," +
                "\"grokSubagents\":" + Json(Environment.GetEnvironmentVariable("GROK_SUBAGENTS")) + "," +
                "\"disable1m\":" + Json(Environment.GetEnvironmentVariable("CLAUDE_CODE_DISABLE_1M_CONTEXT")) + "," +
                "\"disableThinking\":" + Json(Environment.GetEnvironmentVariable("CLAUDE_CODE_DISABLE_THINKING")) + "," +
                "\"unrelatedSecret\":" + Json(Environment.GetEnvironmentVariable("UNRELATED_CLIENT_SECRET")) + "," +
                "\"githubToken\":" + Json(Environment.GetEnvironmentVariable("GH_TOKEN")) + "," +
                "\"awsKey\":" + Json(Environment.GetEnvironmentVariable("AWS_ACCESS_KEY_ID")) + "," +
                "\"databaseUrl\":" + Json(Environment.GetEnvironmentVariable("DATABASE_URL")) + "," +
                "\"githubPat\":" + Json(Environment.GetEnvironmentVariable("GITHUB_PAT")) + "," +
                "\"slackWebhook\":" + Json(Environment.GetEnvironmentVariable("SLACK_WEBHOOK_URL")) + "," +
                "\"codexHome\":" + Json(Environment.GetEnvironmentVariable("CODEX_HOME")) + "," +
                "\"claudeHome\":" + Json(Environment.GetEnvironmentVariable("CLAUDE_CONFIG_DIR")) + "," +
                "\"grokHome\":" + Json(Environment.GetEnvironmentVariable("GROK_HOME")) + "," +
                "\"path\":" + Json(Environment.GetEnvironmentVariable("PATH")) + "," +
                "\"systemRoot\":" + Json(Environment.GetEnvironmentVariable("SystemRoot")) + "," +
                "\"userProfile\":" + Json(Environment.GetEnvironmentVariable("USERPROFILE")) + "," +
                "\"temp\":" + Json(Environment.GetEnvironmentVariable("TEMP")) + "," +
                "\"tmp\":" + Json(Environment.GetEnvironmentVariable("TMP")) + "," +
                "\"gitOptionalLocks\":" + Json(Environment.GetEnvironmentVariable("GIT_OPTIONAL_LOCKS")) + "," +
                "\"gitTerminalPrompt\":" + Json(Environment.GetEnvironmentVariable("GIT_TERMINAL_PROMPT")) + "," +
                "\"gcmInteractive\":" + Json(Environment.GetEnvironmentVariable("GCM_INTERACTIVE")) + "," +
                "\"psModulePath\":" + Json(Environment.GetEnvironmentVariable("PSModulePath")) +
            "}}";
        File.AppendAllText(logPath, entry + Environment.NewLine, new UTF8Encoding(false));
    }

    public static int Main(string[] args)
    {
        string exe = Process.GetCurrentProcess().MainModule.FileName ?? "fake";
        string provider = Path.GetFileNameWithoutExtension(exe).ToLowerInvariant();
        string stateRoot = Path.GetDirectoryName(exe) ?? Environment.CurrentDirectory;
        string logPath = Path.Combine(stateRoot, "fake-calls.jsonl");
        int pid = Process.GetCurrentProcess().Id;
        bool opusAuth = provider.Contains("opus") && args.Length >= 2 && args[0] == "auth" && args[1] == "status";
        bool codexAuth = provider.Contains("codex") && args.Length >= 2 && args[0] == "login" && args[1] == "status";
        bool authPreflight = opusAuth || codexAuth;
        string kind = authPreflight ? "auth_preflight" : "task";
        string scenarioName = authPreflight ? "fake-auth-scenario.txt" : "fake-task-scenario.txt";
        string scenarioPath = Path.Combine(stateRoot, scenarioName);
        string scenario = File.Exists(scenarioPath) ? File.ReadAllText(scenarioPath, new UTF8Encoding(false, true)) : (authPreflight ? "auth_ok" : "default");
        if (HasArgument(args, "--hold-child")) {
            string pidPath = Path.Combine(stateRoot, "descendant.pid");
            File.WriteAllText(pidPath, pid.ToString(), new UTF8Encoding(false));
            Thread.Sleep(10000);
            return 0;
        }
        if (authPreflight) {
            WriteLog(logPath, kind, provider, args, "", "", pid);
            if (scenario == "auth_mutates_repository") {
                string source = Path.Combine(Environment.CurrentDirectory, "src");
                Directory.CreateDirectory(source);
                File.WriteAllText(Path.Combine(source, "auth-mutated.txt"), "auth mutation", new UTF8Encoding(false));
            }
            if (scenario == "auth_mutates_ignored") {
                File.WriteAllText(Path.Combine(Environment.CurrentDirectory, "ignored-output.tmp"), "ignored auth mutation", new UTF8Encoding(false));
            }
            if (scenario == "auth_mutates_then_restores") {
                string tracked = Path.Combine(Environment.CurrentDirectory, "tracked.txt");
                byte[] original = File.ReadAllBytes(tracked);
                File.WriteAllText(tracked, "transient auth mutation", new UTF8Encoding(false));
                File.WriteAllBytes(tracked, original);
            }
            if (scenario == "auth_timeout") { Thread.Sleep(60000); return 0; }
            if (scenario == "auth_output_limit") {
                Console.Out.Write(new string('A', 70000));
                Console.Out.Flush();
                Thread.Sleep(10000);
                return 0;
            }
            if (scenario == "auth_fail") {
                Console.Out.Write("AUTH_PREFLIGHT_SECRET_CANARY");
                Console.Error.Write("AUTH_PREFLIGHT_SECRET_CANARY");
                return 77;
            }
            Console.Out.Write("{\"authenticated\":true,\"private\":\"AUTH_PREFLIGHT_SECRET_CANARY\"}");
            return 0;
        }
        if (scenario == "stdin_hang") {
            WriteLog(logPath, kind, provider, args, "", "", pid);
            byte[] partialUtf8 = new byte[] { 0xF0, 0x9F, 0x92 };
            Stream rawOutput = Console.OpenStandardOutput();
            rawOutput.Write(partialUtf8, 0, partialUtf8.Length);
            rawOutput.Flush();
            Thread.Sleep(10000);
            return 0;
        }
        string stdin = Console.In.ReadToEnd();
        string promptFile = ValueAfter(args, "--prompt-file");
        string task = File.Exists(promptFile) ? File.ReadAllText(promptFile, new UTF8Encoding(false, true)) : stdin;
        WriteLog(logPath, kind, provider, args, stdin, task, pid);

        if (scenario == "timeout") { Thread.Sleep(10000); return 0; }
        if (scenario == "output_limit") {
            Console.Out.Write(new string('X', 70000));
            Console.Out.Flush();
            Thread.Sleep(10000);
            return 0;
        }
        if (scenario == "nonzero") {
            Console.Out.Write("FAKE_STDOUT_SENTINEL");
            Console.Error.Write("FAKE_STDERR_SENTINEL");
            return 73;
        }
        if (scenario == "mutation_nonzero") {
            string source = Path.Combine(Environment.CurrentDirectory, "src");
            Directory.CreateDirectory(source);
            string mutationName = provider.Contains("grok") ? "grok-fake.txt" :
                (provider.Contains("opus") ? "opus-mutated.txt" : "codex-mutated.txt");
            File.WriteAllText(Path.Combine(source, mutationName), "mutation before nonzero", new UTF8Encoding(false));
            Console.Error.Write("FAKE_MUTATION_NONZERO");
            return 73;
        }
        if (scenario == "root_exit_child") {
            ProcessStartInfo childStart = new ProcessStartInfo(exe, "--hold-child");
            childStart.UseShellExecute = false;
            Process child = Process.Start(childStart);
            if (child != null) child.Dispose();
            return 0;
        }

        if (provider.Contains("grok")) {
            if (scenario == "grok_bad_shape") {
                string badReport = "{\"status\":\"NO_CHANGE\",\"summary\":\"fake grok\",\"changed_paths\":[],\"tests\":\"bad\",\"unverified\":[]}";
                Console.Out.Write("{\"text\":" + Json("Inspecting before the final report." + badReport) + ",\"stopReason\":\"end_turn\"}");
                return 0;
            }
            string status = scenario == "blocked" ? "BLOCKED" : (scenario == "grok_no_change" ? "NO_CHANGE" : "COMPLETE");
            string changed = "[]";
            if (status == "COMPLETE") {
                string relative = "src/grok-fake.txt";
                if (scenario == "grok_out_of_scope") relative = "src/forbidden.txt";
                if (scenario == "grok_modify_dirty_wip") relative = "dirty-wip.txt";
                if (scenario == "grok_ignored_change") relative = "ignored-output.tmp";
                if (scenario == "grok_empty_dir_only") relative = "scratch-empty";
                if (scenario == "grok_delete_parent") relative = "delete-tree/child.txt";
                if (scenario == "grok_replace_allowed_file_with_directory") relative = "scope-file.txt/child.txt";
                if (scenario == "grok_empty_dir_only") {
                    Directory.CreateDirectory(Path.Combine(Environment.CurrentDirectory, "scratch-empty"));
                }
                else if (scenario == "grok_delete_parent") {
                    Directory.Delete(Path.Combine(Environment.CurrentDirectory, "delete-tree"), true);
                }
                else if (scenario == "grok_replace_allowed_file_with_directory") {
                    string scopeFile = Path.Combine(Environment.CurrentDirectory, "scope-file.txt");
                    File.Delete(scopeFile);
                    Directory.CreateDirectory(scopeFile);
                    File.WriteAllText(Path.Combine(scopeFile, "child.txt"), "scope escape", new UTF8Encoding(false));
                }
                else if (scenario != "grok_false_complete") {
                    string destination = Path.Combine(Environment.CurrentDirectory, relative.Replace('/', Path.DirectorySeparatorChar));
                    string destinationDirectory = Path.GetDirectoryName(destination);
                    if (!String.IsNullOrEmpty(destinationDirectory)) Directory.CreateDirectory(destinationDirectory);
                    File.WriteAllText(destination, "grok writer", new UTF8Encoding(false));
                }
                string reported = scenario == "grok_report_mismatch" ? "src/reported-only.txt" : relative;
                changed = "[" + Json(reported) + "]";
            }
            string summary = scenario == "grok_brace_heavy" ? new string('{', 80) : "fake grok";
            string report = "{\"status\":" + Json(status) + ",\"summary\":" + Json(summary) + ",\"changed_paths\":" + changed + ",\"tests\":[\"fake\"],\"unverified\":[]}";
            if (scenario == "grok_extra_field") report = report.Substring(0, report.Length - 1) + ",\"extra\":true}";
            if (scenario == "grok_lowercase_status") report = report.Replace("\"COMPLETE\"", "\"complete\"");
            if (scenario == "grok_duplicate_status") report = report.Replace("\"status\":\"COMPLETE\"", "\"status\":\"COMPLETE\",\"status\":\"BLOCKED\"");
            if (scenario == "grok_duplicate_changed_paths") report = report.Replace("\"changed_paths\":" + changed, "\"changed_paths\":" + changed + ",\"changed_paths\":[]");
            Console.Error.WriteLine("FAKE_GROK_PROGRESS_BEFORE_FINAL_REPORT");
            string stopReason = scenario == "grok_cancelled_report" ? "cancelled" : "end_turn";
            string envelope = scenario == "grok_array_report"
                ? "{\"structured_output\":[" + report + "]"
                : "{\"text\":" + Json("Inspecting and editing before the final report." + report);
            if (scenario != "grok_missing_stop_reason") envelope += ",\"stopReason\":" + Json(stopReason);
            if (scenario == "grok_duplicate_envelope_key") envelope += ",\"stopReason\":\"end_turn\"";
            string finalEnvelope = envelope + "}";
            if (scenario == "grok_array_envelope") finalEnvelope = "[" + finalEnvelope + "]";
            Console.Out.Write(finalEnvelope);
            return 0;
        }
        if (provider.Contains("opus")) {
            if (scenario == "opus_mutates") {
                string source = Path.Combine(Environment.CurrentDirectory, "src");
                Directory.CreateDirectory(source);
                File.WriteAllText(Path.Combine(source, "opus-mutated.txt"), "opus mutation", new UTF8Encoding(false));
            }
            if (scenario == "opus_mutates_dirty") {
                File.WriteAllText(Path.Combine(Environment.CurrentDirectory, "dirty-wip.txt"), "opus changed dirty WIP", new UTF8Encoding(false));
            }
            string verdict = scenario == "opus_fail" ? "FAIL" : (scenario == "blocked" ? "BLOCKED" : "PASS");
            string findings = verdict == "FAIL" ? "[{\"severity\":\"HIGH\",\"file\":\"src/a.cs\",\"line\":1,\"title\":\"fake\",\"detail\":\"fake defect\"}]" : "[]";
            string report = "{\"verdict\":" + Json(verdict) + ",\"summary\":\"fake opus\",\"findings\":" + findings + ",\"unverified\":[]}";
            if (scenario == "opus_bad_shape") report = "{\"verdict\":\"PASS\",\"summary\":7,\"findings\":[],\"unverified\":[]}";
            if (scenario == "opus_bad_array") report = "{\"verdict\":\"PASS\",\"summary\":\"fake opus\",\"findings\":[],\"unverified\":\"not-array\"}";
            if (scenario == "opus_bad_finding") report = "{\"verdict\":\"FAIL\",\"summary\":\"fake opus\",\"findings\":[{\"severity\":\"URGENT\",\"file\":\"src/a.cs\",\"line\":\"1\",\"title\":\"fake\",\"detail\":\"fake defect\"}],\"unverified\":[]}";
            if (scenario == "opus_extra_field") report = "{\"verdict\":\"PASS\",\"summary\":\"fake opus\",\"findings\":[],\"unverified\":[],\"extra\":true}";
            if (scenario == "opus_prose_report") report = "Review complete. " + report;
            if (scenario == "opus_array_report") report = "[" + report + "]";
            if (scenario == "opus_invalid_envelope") { Console.Out.Write("not-json"); return 0; }
            string subtype = scenario == "opus_error_envelope" ? "error_max_structured_output_retries" : "success";
            string isError = scenario == "opus_error_envelope" ? "true" : "false";
            string envelope = "{\"type\":\"result\",\"subtype\":" + Json(subtype) + ",\"is_error\":" + isError;
            if (scenario != "opus_missing_result") envelope += ",\"result\":" + Json(report);
            if (scenario == "opus_incomplete_terminal") envelope += ",\"terminal_reason\":\"aborted_streaming\"";
            string finalEnvelope = envelope + "}";
            if (scenario == "opus_array_envelope") finalEnvelope = "[" + finalEnvelope + "]";
            Console.Out.Write(finalEnvelope);
            return 0;
        }
        if (provider.Contains("codex")) {
            if (scenario == "codex_mutates") {
                string source = Path.Combine(Environment.CurrentDirectory, "src");
                Directory.CreateDirectory(source);
                File.WriteAllText(Path.Combine(source, "codex-mutated.txt"), "codex mutation", new UTF8Encoding(false));
            }
            if (scenario == "codex_mutates_dirty") {
                File.WriteAllText(Path.Combine(Environment.CurrentDirectory, "dirty-wip.txt"), "codex changed dirty WIP", new UTF8Encoding(false));
            }
            if (scenario == "codex_mutates_ignored") {
                File.WriteAllText(Path.Combine(Environment.CurrentDirectory, "ignored-output.tmp"), "ignored mutation", new UTF8Encoding(false));
            }
            string finalPath = ValueAfter(args, "--output-last-message");
            string model = ValueAfter(args, "--model");
            string mode = model == "gpt-5.3-codex-spark" ? "simple_test" : "review";
            const string modeMarker = "Set mode=";
            int modeMarkerIndex = task.IndexOf(modeMarker, StringComparison.Ordinal);
            if (modeMarkerIndex >= 0) {
                int modeStart = modeMarkerIndex + modeMarker.Length;
                int modeEnd = task.IndexOfAny(new char[] { '\r', '\n' }, modeStart);
                if (modeEnd < 0) modeEnd = task.Length;
                string modeText = task.Substring(modeStart, modeEnd - modeStart).Trim();
                int commaIndex = modeText.IndexOf(',');
                if (commaIndex >= 0) modeText = modeText.Substring(0, commaIndex);
                mode = modeText.Trim().TrimEnd('.');
            }
            string verdict = scenario == "blocked" ? "NOT_APPLICABLE" : (scenario == "codex_fail" ? "FAIL" : "PASS");
            string status = scenario == "blocked" ? "BLOCKED" : "COMPLETE";
            string changedPaths = scenario == "codex_changed_path" ? "[\"src/forbidden.txt\"]" : "[]";
            string findings = verdict == "FAIL" ? "[{\"severity\":\"HIGH\",\"file\":\"src/a.cs\",\"line\":1,\"title\":\"fake\",\"detail\":\"fake defect\"}]" : "[]";
            string report = "{" +
                "\"mode\":" + Json(mode) + "," +
                "\"status\":" + Json(status) + "," +
                "\"verdict\":" + Json(verdict) + "," +
                "\"summary\":\"fake codex\"," +
                "\"findings\":" + findings + "," +
                "\"changed_paths\":" + changedPaths + "," +
                "\"tests\":[\"fake\"]," +
                "\"unverified\":[]}";
            if (scenario == "codex_bad_shape") report = "{\"mode\":" + Json(mode) + ",\"status\":\"COMPLETE\",\"verdict\":\"PASS\",\"summary\":9,\"findings\":[],\"changed_paths\":[],\"tests\":[],\"unverified\":[]}";
            if (scenario == "codex_bad_array") report = "{\"mode\":" + Json(mode) + ",\"status\":\"COMPLETE\",\"verdict\":\"PASS\",\"summary\":\"fake codex\",\"findings\":[],\"changed_paths\":[],\"tests\":\"not-array\",\"unverified\":[1]}";
            if (scenario == "codex_bad_finding") report = "{\"mode\":" + Json(mode) + ",\"status\":\"COMPLETE\",\"verdict\":\"FAIL\",\"summary\":\"fake codex\",\"findings\":[{\"severity\":\"URGENT\",\"file\":\"src/a.cs\",\"line\":\"1\",\"title\":\"fake\",\"detail\":\"fake defect\"}],\"changed_paths\":[],\"tests\":[],\"unverified\":[]}";
            if (scenario == "codex_extra_field") report = report.Substring(0, report.Length - 1) + ",\"extra\":true}";
            if (scenario == "codex_invalid_json") report = "not-json";
            if (scenario == "codex_array_report") report = "[" + report + "]";
            if (scenario != "codex_report_missing") File.WriteAllText(finalPath, report, new UTF8Encoding(false));
            Console.Out.Write("FAKE_CODEX_PROGRESS");
            return 0;
        }
        return 91;
    }
}
'@

try {
    [void][System.IO.Directory]::CreateDirectory($script:Repository)
    [void][System.IO.Directory]::CreateDirectory($script:NonGitDirectory)
    [void][System.IO.Directory]::CreateDirectory($script:FakeGitDirectory)
    [void][System.IO.Directory]::CreateDirectory((Join-Path $script:FakeGitDirectory '.git'))
    [System.IO.File]::WriteAllText((Join-Path $script:FakeGitDirectory '.git\HEAD'), 'ref: refs/heads/main', $script:Utf8)
    [System.IO.File]::WriteAllText((Join-Path $script:Repository '.gitignore'), "ignored-output.tmp`r`n", $script:Utf8)
    [System.IO.File]::WriteAllText((Join-Path $script:Repository 'tracked.txt'), 'tracked baseline', $script:Utf8)
    [System.IO.File]::WriteAllText((Join-Path $script:Repository 'scope-file.txt'), 'scope file baseline', $script:Utf8)
    [System.IO.File]::WriteAllText($script:DirtyWipPath, 'committed dirty baseline', $script:Utf8)
    [void](Invoke-AwGitSetup -WorkingDirectory $script:Repository -Arguments @('init', '--initial-branch=main'))
    [void](Invoke-AwGitSetup -WorkingDirectory $script:Repository -Arguments @('add', '--', '.'))
    [void](Invoke-AwGitSetup -WorkingDirectory $script:Repository -Arguments @(
        '-c', 'user.name=AI Wrapper Offline', '-c', 'user.email=offline@example.invalid',
        'commit', '-m', 'offline baseline'
    ))
    [System.IO.File]::WriteAllText($script:DirtyWipPath, 'existing dirty WIP', $script:Utf8)
    [void](Invoke-AwGitSetup -WorkingDirectory $script:Repository -Arguments @(
        'worktree', 'add', '-b', 'offline-linked-worktree', $script:AlternateRepository, 'HEAD'
    ))
    [void][System.IO.Directory]::CreateDirectory((Join-Path $script:Repository 'src'))
    [void][System.IO.Directory]::CreateDirectory((Join-Path $script:AlternateRepository 'src'))
    [void][System.IO.Directory]::CreateDirectory($script:RepositorySubdirectory)
    [void][System.IO.Directory]::CreateDirectory($script:OutsideReparseTarget)
    [void][System.IO.Directory]::CreateDirectory($script:ReparseAllowDirectory)
    [void][System.IO.Directory]::CreateDirectory($script:HardlinkAllowDirectory)
    [void](New-Item -ItemType Junction -Path $script:ReparseDescendant -Target $script:OutsideReparseTarget -ErrorAction Stop)
    [System.IO.File]::WriteAllText($script:OutsideHardlinkTarget, 'outside hardlink bytes', $script:Utf8)
    [void](New-Item -ItemType HardLink -Path $script:HardlinkDescendant -Target $script:OutsideHardlinkTarget -ErrorAction Stop)
    [void][System.IO.Directory]::CreateDirectory($script:GrokAuthHome)
    [System.IO.File]::WriteAllText((Join-Path $script:GrokAuthHome 'auth.json'), '{"fake-profile":{"key":"GROK_AUTH_FILE_CANARY","refresh_token":"GROK_REFRESH_CANARY"}}', $script:Utf8)
    [void][System.IO.Directory]::CreateDirectory($script:RuntimePackage)
    foreach ($name in @('ai-wrapper-core.ps1', 'invoke-grok.ps1', 'invoke-opus.ps1', 'invoke-codex.ps1')) {
        [System.IO.File]::Copy((Join-Path $script:PackageRoot $name), (Join-Path $script:RuntimePackage $name))
    }
    . (Join-Path $script:PackageRoot 'ai-wrapper-core.ps1')
    $fakeBase = Join-Path $script:TestRoot 'fake-base.exe'
    $fakeSourcePath = Join-Path $script:TestRoot 'fake-ai.cs'
    [System.IO.File]::WriteAllText($fakeSourcePath, $fakeSource, $script:Utf8)
    $compilerPath = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    if (-not [System.IO.File]::Exists($compilerPath)) { throw 'WINDOWS_CSHARP_COMPILER_MISSING' }
    $compileStart = [System.Diagnostics.ProcessStartInfo]::new()
    $compileStart.FileName = $compilerPath
    foreach ($argument in @('/nologo', '/target:exe', ('/out:' + $fakeBase), $fakeSourcePath)) {
        [void]$compileStart.ArgumentList.Add($argument)
    }
    $compileStart.UseShellExecute = $false
    $compileStart.CreateNoWindow = $true
    $compileStart.RedirectStandardOutput = $true
    $compileStart.RedirectStandardError = $true
    $compiler = [System.Diagnostics.Process]::new()
    $compiler.StartInfo = $compileStart
    try {
        Assert-Aw -Condition $compiler.Start() -Message 'CSHARP_COMPILER_START_FAILED'
        $compilerOutput = $compiler.StandardOutput.ReadToEndAsync()
        $compilerError = $compiler.StandardError.ReadToEndAsync()
        Assert-Aw -Condition $compiler.WaitForExit(30000) -Message 'CSHARP_COMPILER_TIMEOUT'
        $compileText = [string]$compilerOutput.GetAwaiter().GetResult() + [string]$compilerError.GetAwaiter().GetResult()
        Assert-Aw -Condition ($compiler.ExitCode -eq 0) -Message ('CSHARP_COMPILER_FAILED_' + $compileText)
    }
    finally { $compiler.Dispose() }
    $fakeGrok = Join-Path $script:TestRoot 'fake-grok.exe'
    $fakeOpus = Join-Path $script:TestRoot 'fake-opus.exe'
    $fakeCodex = Join-Path $script:TestRoot 'fake-codex.exe'
    $fakeOfficeGrok = Join-Path $script:TestRoot 'office-grok.exe'
    [System.IO.File]::Copy($fakeBase, $fakeGrok)
    [System.IO.File]::Copy($fakeBase, $fakeOpus)
    [System.IO.File]::Copy($fakeBase, $fakeCodex)
    [System.IO.File]::Copy($fakeBase, $fakeOfficeGrok)

    $config = [ordered]@{
        schemaVersion = 3
        repositoryRoot = ('Z:\disconnected-default-' + [guid]::NewGuid().ToString('N'))
        activeMachineProfile = 'home'
        machineProfiles = [ordered]@{
            home = [ordered]@{
                grokExecutable = $fakeGrok
                opusExecutable = $fakeOpus
                codexExecutable = $fakeCodex
            }
            office = [ordered]@{
                grokExecutable = ''
                opusExecutable = ''
                codexExecutable = ''
            }
        }
        preflightTimeoutSeconds = 30
        grokTimeoutSeconds = 5
        opusTimeoutSeconds = 5
        codexTimeoutSeconds = 5
        maxOutputBytes = 65536
    }
    [System.IO.File]::WriteAllText($script:ConfigPath, ($config | ConvertTo-Json -Depth 20), $script:Utf8)

    Invoke-AwCase 'StaticContract' {
        foreach ($name in @('ai-wrapper-core.ps1', 'invoke-grok.ps1', 'invoke-opus.ps1', 'invoke-codex.ps1')) {
            $path = Join-Path $script:PackageRoot $name
            $tokens = $null
            $errors = $null
            [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors) | Out-Null
            Assert-Aw -Condition (@($errors).Count -eq 0) -Message ($name + '_PARSE_ERROR')
        }
        $coreText = [System.IO.File]::ReadAllText((Join-Path $script:PackageRoot 'ai-wrapper-core.ps1'), $script:Utf8)
        Assert-Aw -Condition (([regex]::Matches($coreText, '\.Start\(\)')).Count -eq 1) -Message 'PROCESS_START_COUNT_NOT_ONE'
        Assert-Aw -Condition ($coreText.Contains('NotifyFilters.FileName | NotifyFilters.DirectoryName', [System.StringComparison]::Ordinal) -and $coreText.Contains('NotifyFilters.LastWrite | NotifyFilters.Size', [System.StringComparison]::Ordinal)) -Message 'WATCHER_CONTENT_FILTERS_MISSING'
        Assert-Aw -Condition (-not $coreText.Contains('NotifyFilters.Attributes', [System.StringComparison]::Ordinal) -and -not $coreText.Contains('NotifyFilters.Security', [System.StringComparison]::Ordinal) -and -not $coreText.Contains('NotifyFilters.CreationTime', [System.StringComparison]::Ordinal)) -Message 'WATCHER_METADATA_FILTER_FALSE_POSITIVE_RISK'
        $strictUtf8FunctionOffset = $coreText.IndexOf('function Get-AwUtf8', [System.StringComparison]::Ordinal)
        Assert-Aw -Condition ($strictUtf8FunctionOffset -gt 0) -Message 'STRICT_UTF8_HELPER_MISSING'
        $consolePreamble = $coreText.Substring(0, $strictUtf8FunctionOffset)
        Assert-Aw -Condition ($consolePreamble.Contains('$script:AwConsoleUtf8 = [System.Text.UTF8Encoding]::new($false)', [System.StringComparison]::Ordinal)) -Message 'CONSOLE_UTF8_INSTANCE_MISSING'
        Assert-Aw -Condition ($consolePreamble.Contains('[Console]::OutputEncoding = $script:AwConsoleUtf8', [System.StringComparison]::Ordinal) -and $consolePreamble.Contains('[Console]::InputEncoding = $script:AwConsoleUtf8', [System.StringComparison]::Ordinal)) -Message 'CONSOLE_UTF8_ASSIGNMENT_MISSING'
        Assert-Aw -Condition (-not $consolePreamble.Contains('Get-AwUtf8', [System.StringComparison]::Ordinal)) -Message 'STRICT_FILE_UTF8_HELPER_USED_FOR_CONSOLE'
        Assert-Aw -Condition (-not [regex]::IsMatch($coreText, '(?i)\$global:OutputEncoding')) -Message 'GLOBAL_OUTPUT_ENCODING_PRESENT'
        $wrapperText = @('invoke-grok.ps1', 'invoke-opus.ps1', 'invoke-codex.ps1') | ForEach-Object {
            [System.IO.File]::ReadAllText((Join-Path $script:PackageRoot $_), $script:Utf8)
        }
        $joined = $wrapperText -join "`n"
        foreach ($forbidden in @('--version', 'spawn_subagent', 'Get-Command')) {
            Assert-Aw -Condition (-not $joined.Contains($forbidden, [System.StringComparison]::OrdinalIgnoreCase)) -Message ('FORBIDDEN_TEXT_' + $forbidden)
        }
        Assert-Aw -Condition ($joined.Contains('--no-subagents', [System.StringComparison]::Ordinal)) -Message 'GROK_NO_SUBAGENTS_MISSING'
        Assert-Aw -Condition ($joined.Contains('features.multi_agent=false', [System.StringComparison]::Ordinal)) -Message 'CODEX_MULTI_AGENT_DISABLE_MISSING'
        $codexText = [System.IO.File]::ReadAllText((Join-Path $script:PackageRoot 'invoke-codex.ps1'), $script:Utf8)
        Assert-Aw -Condition (-not [regex]::IsMatch($codexText, '(?i)(\$Implement|mode=implement|''implement'')')) -Message 'CODEX_IMPLEMENT_SURFACE_PRESENT'
        Assert-Aw -Condition (-not $codexText.Contains('allow_login_shell=false', [System.StringComparison]::OrdinalIgnoreCase)) -Message 'CODEX_LOGIN_SHELL_EXEC_BLOCK_PRESENT'
        Assert-Aw -Condition ($codexText.Contains('windows.sandbox="elevated"', [System.StringComparison]::Ordinal)) -Message 'CODEX_ELEVATED_WINDOWS_SANDBOX_MISSING'
        Assert-Aw -Condition (-not $joined.Contains('ConfigPath', [System.StringComparison]::OrdinalIgnoreCase)) -Message 'PUBLIC_CONFIG_PATH_OVERRIDE_PRESENT'
    }

    Invoke-AwCase 'WatcherInternalErrorClassifiedSeparatelyFromMutation' {
        $indexEntries = New-AwStringDictionary
        $worktreeEntries = New-AwStringDictionary
        $snapshot = [pscustomobject]@{
            TopLevel = $script:Repository
            GitDirectory = (Join-Path $script:Repository '.git')
            GitCommonDirectory = (Join-Path $script:Repository '.git')
            Head = 'probe-head'
            HeadRef = 'refs/heads/main'
            IndexEntries = $indexEntries
            WorktreeEntries = $worktreeEntries
        }
        $watcherResult = [pscustomobject]@{
            Paths = @()
            HasError = $true
            ErrorCount = 1
            Errors = @('OFFLINE_WATCHER_ERROR_PROBE')
        }
        $failure = ''
        $originalError = [Console]::Error
        $capturedError = [System.IO.StringWriter]::new()
        try {
            [Console]::SetError($capturedError)
            try {
                Assert-AwReadOnlyRepositoryUnchanged -Before $snapshot -After $snapshot `
                    -Provider CODEX -WatcherResult $watcherResult
            }
            catch { $failure = [string]$_.Exception.Message }
        }
        finally {
            [Console]::SetError($originalError)
            $diagnostic = $capturedError.ToString()
            $capturedError.Dispose()
        }
        Assert-Aw -Condition ($failure -ceq 'CODEX_REPOSITORY_WATCHER_UNRELIABLE') -Message ('WATCHER_ERROR_MISCLASSIFIED_' + $failure)
        Assert-Aw -Condition ((Get-AwWrapperErrorExitCode -Message $failure) -eq 70) -Message 'WATCHER_ERROR_EXIT_NOT_70'
        Assert-Aw -Condition ($diagnostic.Contains('watcher_errors=1', [System.StringComparison]::Ordinal) -and $diagnostic.Contains('OFFLINE_WATCHER_ERROR_PROBE', [System.StringComparison]::Ordinal)) -Message 'WATCHER_ERROR_DIAGNOSTIC_MISSING'
    }

    Invoke-AwCase 'WatcherIgnoresAttributeOnlyChanges' {
        $target = Join-Path $script:Repository 'tracked.txt'
        $originalAttributes = [System.IO.File]::GetAttributes($target)
        $hidden = [System.IO.FileAttributes]::Hidden
        $temporaryAttributes = if (($originalAttributes -band $hidden) -ne 0) {
            [System.IO.FileAttributes]([int]$originalAttributes -band (-bnot [int]$hidden))
        }
        else { [System.IO.FileAttributes]([int]$originalAttributes -bor [int]$hidden) }
        $beforeAttributes = Get-AwStableRepositorySnapshot -Root $script:Repository
        $attributeWatcher = Start-AwRepositoryWatcher -Root $script:Repository
        $attributeWatcherResult = $null
        try {
            [System.IO.File]::SetAttributes($target, $temporaryAttributes)
            [System.IO.File]::SetAttributes($target, $originalAttributes)
            Start-Sleep -Milliseconds 100
            $attributeWatcherResult = Stop-AwRepositoryWatcher -Watcher $attributeWatcher
            $attributeWatcher = $null
        }
        finally {
            [System.IO.File]::SetAttributes($target, $originalAttributes)
            if ($null -ne $attributeWatcher) { $attributeWatcher.Dispose() }
        }
        $afterAttributes = Get-AwStableRepositorySnapshot -Root $script:Repository
        Assert-Aw -Condition (@($attributeWatcherResult.Paths).Count -eq 0) -Message 'ATTRIBUTE_ONLY_EVENT_REPORTED_AS_MUTATION'
        Assert-Aw -Condition (-not [bool]$attributeWatcherResult.HasError) -Message 'ATTRIBUTE_ONLY_WATCHER_ERROR'
        Assert-AwReadOnlyRepositoryUnchanged -Before $beforeAttributes -After $afterAttributes `
            -Provider CODEX -WatcherResult $attributeWatcherResult
    }

    Invoke-AwCase 'Cp949ParentConsoleEmissionIsStrictUtf8' {
        $result = Invoke-AwCp949ConsoleUtf8Probe
        $expectedStdOut = '표준출력 한글'
        $expectedStdErr = '표준오류 한글'
        Assert-Aw -Condition ($result.StdOut -ceq $expectedStdOut) -Message 'CP949_STDOUT_STRICT_UTF8_DECODE_FAILED'
        Assert-Aw -Condition ($result.StdErr -ceq $expectedStdErr) -Message 'CP949_STDERR_STRICT_UTF8_DECODE_FAILED'
        Assert-Aw -Condition ([System.Linq.Enumerable]::SequenceEqual[byte]($result.StdOutBytes, $script:Utf8.GetBytes($expectedStdOut))) -Message 'CP949_STDOUT_RAW_BYTES_NOT_UTF8'
        Assert-Aw -Condition ([System.Linq.Enumerable]::SequenceEqual[byte]($result.StdErrBytes, $script:Utf8.GetBytes($expectedStdErr))) -Message 'CP949_STDERR_RAW_BYTES_NOT_UTF8'
    }

    Invoke-AwCase 'CanonicalLocalAppDataTempAndAllowlistHelpers' {
        . (Join-Path $script:PackageRoot 'ai-wrapper-core.ps1')
        $originalTemp = $env:TEMP
        $originalTmp = $env:TMP
        try {
            $env:TEMP = 'C:\WINDOWS\TEMP'
            $env:TMP = 'C:\WINDOWS\TEMP'
            $expectedBase = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Temp'))
            $actualBase = Get-AwTempBase
            Assert-Aw -Condition ($actualBase.Equals($expectedBase, [System.StringComparison]::OrdinalIgnoreCase)) -Message 'CANONICAL_TEMP_BASE'
            $tempProbe = New-AwTempDirectory -Prefix 'ai-wrapper-helper-' -Base $actualBase
            Assert-Aw -Condition ([System.IO.Directory]::Exists($tempProbe)) -Message 'CANONICAL_TEMP_CREATE'
            Remove-AwTempDirectory -Path $tempProbe -Prefix 'ai-wrapper-helper-' -Base $actualBase
            Assert-Aw -Condition (-not [System.IO.Directory]::Exists($tempProbe)) -Message 'CANONICAL_TEMP_CLEANUP'
            $resolvedRoot = Resolve-AwRepositoryRoot -ConfiguredRoot $script:Repository -RepositoryRoot $script:Repository
            $resolvedAllowlist = @(Resolve-AwWriteAllowlist -Root $resolvedRoot -Paths @('src/grok-fake.txt'))
            Assert-Aw -Condition ($resolvedAllowlist.Count -eq 1 -and $resolvedAllowlist[0] -ceq 'src/grok-fake.txt') -Message 'WRITE_ALLOWLIST_RESOLUTION'
            $absoluteAllowlist = @(Resolve-AwWriteAllowlist -Root $resolvedRoot -Paths @((Join-Path $resolvedRoot 'src\grok-fake.txt')))
            Assert-Aw -Condition ($absoluteAllowlist.Count -eq 1 -and $absoluteAllowlist[0] -ceq 'src/grok-fake.txt') -Message 'WRITE_ALLOWLIST_ABSOLUTE_RESOLUTION'
            $fileAllowlist = @(Resolve-AwWriteAllowlist -Root $resolvedRoot -Paths @('scope-file.txt'))
            Assert-Aw -Condition (-not (Test-AwPathWithinAllowlist -RelativePath 'scope-file.txt/child.txt' -Allowlist $fileAllowlist)) -Message 'WRITE_ALLOWLIST_FILE_DESCENDANT_ALLOWED'
            $directoryAllowlist = @(Resolve-AwWriteAllowlist -Root $resolvedRoot -Paths @('src'))
            Assert-Aw -Condition ($directoryAllowlist.Count -eq 1 -and $directoryAllowlist[0] -ceq 'src/' -and (Test-AwPathWithinAllowlist -RelativePath 'src/child.txt' -Allowlist $directoryAllowlist)) -Message 'WRITE_ALLOWLIST_DIRECTORY_DESCENDANT_DENIED'
            $missingAllowlist = @(Resolve-AwWriteAllowlist -Root $resolvedRoot -Paths @('missing-scope'))
            Assert-Aw -Condition (-not (Test-AwPathWithinAllowlist -RelativePath 'missing-scope/child.txt' -Allowlist $missingAllowlist)) -Message 'WRITE_ALLOWLIST_MISSING_DESCENDANT_ALLOWED'
        }
        finally {
            $env:TEMP = $originalTemp
            $env:TMP = $originalTmp
        }
    }

    Invoke-AwCase 'CodexAutoUpdatePathRecoverySelectsNewestNativeExe' {
        $resolverLocalAppData = Join-Path $script:TestRoot 'resolver-localappdata'
        $resolverBin = Join-Path $resolverLocalAppData 'OpenAI\Codex\bin'
        $staleDirectory = Join-Path $resolverBin 'aaaaaaaaaaaaaaaa'
        $olderDirectory = Join-Path $resolverBin 'bbbbbbbbbbbbbbbb'
        $newerDirectory = Join-Path $resolverBin 'cccccccccccccccc'
        foreach ($directory in @($staleDirectory, $olderDirectory, $newerDirectory)) {
            [void][System.IO.Directory]::CreateDirectory($directory)
        }
        $olderExecutable = Join-Path $olderDirectory 'codex.exe'
        $newerExecutable = Join-Path $newerDirectory 'codex.exe'
        [System.IO.File]::Copy($fakeBase, $olderExecutable)
        [System.IO.File]::Copy($fakeBase, $newerExecutable)
        [System.IO.File]::SetLastWriteTimeUtc($olderExecutable, [datetime]::UtcNow.AddHours(-2))
        [System.IO.File]::SetLastWriteTimeUtc($newerExecutable, [datetime]::UtcNow.AddHours(-1))
        $staleExecutable = Join-Path $staleDirectory 'codex.exe'
        $recovered = Resolve-AwCodexAutoUpdatedExecutable `
            -ConfiguredPath $staleExecutable -LocalAppDataRoot $resolverLocalAppData
        Assert-Aw -Condition ($recovered.Equals($newerExecutable, [System.StringComparison]::OrdinalIgnoreCase)) `
            -Message ('CODEX_AUTO_UPDATE_RECOVERY_WRONG_' + $recovered)
        $outside = Resolve-AwCodexAutoUpdatedExecutable `
            -ConfiguredPath (Join-Path $script:TestRoot 'outside\codex.exe') -LocalAppDataRoot $resolverLocalAppData
        Assert-Aw -Condition ([string]::IsNullOrEmpty($outside)) -Message 'CODEX_AUTO_UPDATE_RECOVERY_ESCAPED_LAYOUT'
    }

    Invoke-AwCase 'WriteAllowlistReparseDescendantRejected' {
        $thrown = ''
        try { [void](Resolve-AwWriteAllowlist -Root $script:Repository -Paths @('allowed-tree')) }
        catch { $thrown = [string]$_.Exception.Message }
        Assert-Aw -Condition ($thrown -eq 'WRITE_ALLOWLIST_REPARSE_POINT_FORBIDDEN') -Message ('REPARSE_ALLOWLIST_NOT_REJECTED_' + $thrown)
    }

    Invoke-AwCase 'GrokReadOnlyMutationErrorMapsToContractExit' {
        Assert-Aw -Condition ((Get-AwWrapperErrorExitCode -Message 'GROK_READ_ONLY_REPOSITORY_MUTATED') -eq 20) -Message 'GROK_AUTH_MUTATION_EXIT_NOT_20'
    }

    Invoke-AwCase 'WriteAllowlistHardlinkRejected' {
        $relative = [System.IO.Path]::GetRelativePath($script:Repository, $script:HardlinkDescendant)
        $thrown = ''
        try { [void](Resolve-AwWriteAllowlist -Root $script:Repository -Paths @($relative)) }
        catch { $thrown = [string]$_.Exception.Message }
        Assert-Aw -Condition ($thrown -eq 'WRITE_ALLOWLIST_HARDLINK_FORBIDDEN') -Message ('HARDLINK_ALLOWLIST_NOT_REJECTED_' + $thrown)
    }

    Invoke-AwCase 'InvalidConfigStartsNoAI' {
        $before = Get-AwCallCount
        $original = $config.machineProfiles.home.grokExecutable
        try {
            $config.machineProfiles.home.grokExecutable = 'relative.cmd'
            [System.IO.File]::WriteAllText($script:ConfigPath, ($config | ConvertTo-Json -Depth 20), $script:Utf8)
            $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'default'
            Assert-Aw -Condition ($result.ExitCode -eq 64) -Message ('EXPECTED_64_GOT_' + $result.ExitCode)
            Assert-Aw -Condition ((Get-AwCallCount) -eq $before) -Message 'AI_STARTED_FOR_BAD_CONFIG'
        }
        finally {
            $config.machineProfiles.home.grokExecutable = $original
            [System.IO.File]::WriteAllText($script:ConfigPath, ($config | ConvertTo-Json -Depth 20), $script:Utf8)
        }
    }

    Invoke-AwCase 'EnvironmentTemplateExecutablePath' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $original = $config.machineProfiles.home.grokExecutable
        $localRoot = [System.IO.Path]::GetFullPath([string]$env:LOCALAPPDATA).TrimEnd([char]'\', [char]'/')
        $fakeFull = [System.IO.Path]::GetFullPath($fakeGrok)
        $localPrefix = $localRoot + [System.IO.Path]::DirectorySeparatorChar
        Assert-Aw -Condition ($fakeFull.StartsWith($localPrefix, [System.StringComparison]::OrdinalIgnoreCase)) -Message 'TEMPLATE_TEST_EXECUTABLE_OUTSIDE_LOCALAPPDATA'
        try {
            $config.machineProfiles.home.grokExecutable = '%LOCALAPPDATA%' + $fakeFull.Substring($localRoot.Length)
            [System.IO.File]::WriteAllText($script:ConfigPath, ($config | ConvertTo-Json -Depth 20), $script:Utf8)
            $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'default'
            Assert-Aw -Condition ($result.ExitCode -eq 0) -Message ('TEMPLATE_EXECUTABLE_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
            Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'TEMPLATE_EXECUTABLE_TASK_COUNT'
            Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq $beforePreflight) -Message 'TEMPLATE_EXECUTABLE_PREFLIGHT_COUNT'
            $call = Read-AwLastTaskCall
            Assert-Aw -Condition ([string]$call.provider -eq 'fake-grok') -Message 'TEMPLATE_EXECUTABLE_NOT_SELECTED'
        }
        finally {
            $config.machineProfiles.home.grokExecutable = $original
            [System.IO.File]::WriteAllText($script:ConfigPath, ($config | ConvertTo-Json -Depth 20), $script:Utf8)
        }
    }

    Invoke-AwCase 'InvalidPromptStartsNoNative' {
        $before = Get-AwCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-opus.ps1' -Scenario 'default' -PromptText ''
        Assert-Aw -Condition ($result.ExitCode -eq 64) -Message ('INVALID_PROMPT_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwCallCount) -eq $before) -Message 'NATIVE_STARTED_FOR_INVALID_PROMPT'
    }

    Invoke-AwCase 'MissingDefaultRequiresExplicitRepository' {
        $before = Get-AwCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'default' -NoRepositoryOverride
        Assert-Aw -Condition ($result.ExitCode -eq 64) -Message ('MISSING_DEFAULT_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwCallCount) -eq $before) -Message 'AI_STARTED_FOR_MISSING_DEFAULT_REPO'
    }

    Invoke-AwCase 'NonGitRepositoryStartsNoNative' {
        $before = Get-AwCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default' -RepositoryRoot $script:NonGitDirectory
        Assert-Aw -Condition ($result.ExitCode -eq 64) -Message ('NON_GIT_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwCallCount) -eq $before) -Message 'NATIVE_STARTED_FOR_NON_GIT_ROOT'
    }

    Invoke-AwCase 'FakeGitMarkerStartsNoNative' {
        $before = Get-AwCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default' -RepositoryRoot $script:FakeGitDirectory
        Assert-Aw -Condition ($result.ExitCode -eq 64) -Message ('FAKE_GIT_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwCallCount) -eq $before) -Message 'NATIVE_STARTED_FOR_FAKE_GIT_ROOT'
        Assert-Aw -Condition ($result.StdErr.Contains('REPOSITORY_ROOT_GIT_', [System.StringComparison]::Ordinal)) -Message 'FAKE_GIT_ERROR_MISSING'
    }

    Invoke-AwCase 'GitSubdirectoryStartsNoNative' {
        $before = Get-AwCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default' -RepositoryRoot $script:RepositorySubdirectory
        Assert-Aw -Condition ($result.ExitCode -eq 64) -Message ('GIT_SUBDIRECTORY_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwCallCount) -eq $before) -Message 'NATIVE_STARTED_FOR_GIT_SUBDIRECTORY'
    }

    Invoke-AwCase 'GrokMissingWriteAllowlistStartsNoNative' {
        $before = Get-AwCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'default' -NoDefaultWriteAllowlist
        Assert-Aw -Condition ($result.ExitCode -eq 64) -Message ('GROK_ALLOWLIST_REQUIRED_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwCallCount) -eq $before) -Message 'NATIVE_STARTED_WITHOUT_GROK_ALLOWLIST'
        Assert-Aw -Condition ($result.StdErr.Contains('WRAPPER_ERROR=WRITE_ALLOWLIST_REQUIRED', [System.StringComparison]::Ordinal)) -Message 'GROK_ALLOWLIST_REQUIRED_ERROR'
    }

    Invoke-AwCase 'ExplicitRepositoryOverrideSelectsExactClone' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'default' -RepositoryRoot $script:AlternateRepository
        Assert-Aw -Condition ($result.ExitCode -eq 0) -Message ('REPOSITORY_OVERRIDE_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'REPOSITORY_OVERRIDE_TASK_COUNT'
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq $beforePreflight) -Message 'GROK_UNEXPECTED_PREFLIGHT_PROCESS'
        $call = Read-AwLastTaskCall
        Assert-Aw -Condition ([string]$call.cwd -eq $script:AlternateRepository) -Message 'REPOSITORY_OVERRIDE_CWD'
        Assert-Aw -Condition ([System.IO.File]::Exists((Join-Path $script:AlternateRepository '.git'))) -Message 'LINKED_WORKTREE_GIT_FILE_MISSING'
        Assert-Aw -Condition ([System.IO.File]::Exists((Join-Path $script:AlternateRepository 'src\grok-fake.txt'))) -Message 'REPOSITORY_OVERRIDE_WRITE_MISSING'
        Assert-Aw -Condition ([System.IO.File]::ReadAllText($script:DirtyWipPath, $script:Utf8) -eq 'existing dirty WIP') -Message 'REPOSITORY_OVERRIDE_TOUCHED_OTHER_WIP'
    }

    Invoke-AwCase 'OfficeExecutableSlot' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $empty = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'default' -ExtraArguments @('-MachineProfile', 'office')
        Assert-Aw -Condition ($empty.ExitCode -eq 64) -Message ('EMPTY_OFFICE_EXIT_' + $empty.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq $beforeTask -and (Get-AwPreflightCallCount) -eq $beforePreflight) -Message 'NATIVE_STARTED_FOR_EMPTY_OFFICE_SLOT'
        try {
            $config.machineProfiles.office.grokExecutable = $fakeOfficeGrok
            [System.IO.File]::WriteAllText($script:ConfigPath, ($config | ConvertTo-Json -Depth 20), $script:Utf8)
            $filled = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'default' -ExtraArguments @('-MachineProfile', 'office')
            Assert-Aw -Condition ($filled.ExitCode -eq 0) -Message ('FILLED_OFFICE_EXIT_' + $filled.ExitCode + '_' + $filled.StdErr)
            Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'OFFICE_TASK_COUNT'
            Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq $beforePreflight) -Message 'OFFICE_GROK_UNEXPECTED_PREFLIGHT_PROCESS'
            $call = Read-AwLastTaskCall
            Assert-Aw -Condition ([string]$call.provider -eq 'office-grok') -Message 'OFFICE_EXECUTABLE_NOT_SELECTED'
        }
        finally {
            $config.machineProfiles.office.grokExecutable = ''
            [System.IO.File]::WriteAllText($script:ConfigPath, ($config | ConvertTo-Json -Depth 20), $script:Utf8)
        }
    }

    Invoke-AwCase 'GrokWriterOneCall' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'default'
        Assert-Aw -Condition ($result.ExitCode -eq 0) -Message ('GROK_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'GROK_TASK_COUNT'
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq $beforePreflight) -Message 'GROK_UNEXPECTED_PREFLIGHT_PROCESS'
        $call = Read-AwLastTaskCall
        Assert-Aw -Condition ([string]$call.cwd -eq $script:Repository) -Message 'GROK_CWD'
        Assert-Aw -Condition ([string]$call.task -eq '오프라인 계약 검증 task & 100%') -Message 'GROK_PROMPT_ROUNDTRIP'
        Assert-Aw -Condition (-not ($call.args -contains '오프라인 계약 검증 task & 100%')) -Message 'GROK_PROMPT_IN_ARGV'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '--model' 'grok-4.5') -Message 'GROK_MODEL'
        Assert-Aw -Condition ($call.args -contains '--always-approve') -Message 'GROK_ALWAYS_APPROVE'
        Assert-Aw -Condition (-not ($call.args -contains '--permission-mode')) -Message 'GROK_PERMISSION_MODE_MUST_BE_ABSENT'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '--tools' 'read_file,search_replace,grep,list_dir') -Message 'GROK_TOOLS'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '--output-format' 'json') -Message 'GROK_OUTPUT_FORMAT'
        Assert-Aw -Condition (-not ($call.args -contains '--json-schema')) -Message 'GROK_JSON_SCHEMA_MUST_NOT_CONSTRAIN_TURNS'
        Assert-Aw -Condition ($call.args -contains '--no-subagents') -Message 'GROK_NO_SUBAGENTS'
        Assert-Aw -Condition ([string]$call.env.grokSubagents -eq '0') -Message 'GROK_SUBAGENTS_ENV'
        Assert-Aw -Condition ($null -eq $call.env.openai -and $null -eq $call.env.anthropic) -Message 'GROK_CROSS_PROVIDER_SECRET'
        Assert-Aw -Condition ([string]$call.env.xai -eq 'XAI_CANARY') -Message 'GROK_OWN_SECRET_REMOVED'
        Assert-Aw -Condition ($null -eq $call.env.unrelatedSecret -and $null -eq $call.env.githubToken -and $null -eq $call.env.awsKey -and $null -eq $call.env.databaseUrl -and $null -eq $call.env.githubPat -and $null -eq $call.env.slackWebhook) -Message 'GROK_GENERIC_SECRET_LEAK'
        Assert-Aw -Condition ([string]$call.env.grokHome -eq 'GROK_HOME_CANARY' -and $null -eq $call.env.codexHome -and $null -eq $call.env.claudeHome) -Message 'GROK_PROVIDER_HOME_ISOLATION'
        Assert-Aw -Condition (-not [string]::IsNullOrWhiteSpace([string]$call.env.path) -and -not [string]::IsNullOrWhiteSpace([string]$call.env.systemRoot) -and -not [string]::IsNullOrWhiteSpace([string]$call.env.userProfile)) -Message 'GROK_REQUIRED_OS_ENV_MISSING'
        $expectedChildTemp = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Temp'))
        Assert-Aw -Condition ([string]$call.env.temp -eq $expectedChildTemp -and [string]$call.env.tmp -eq $expectedChildTemp) -Message 'GROK_CHILD_TEMP_NOT_CANONICAL'
        Assert-Aw -Condition ($null -eq $call.env.psModulePath) -Message 'GROK_CHILD_PSMODULEPATH_INHERITED'
        $grokRules = Get-AwArgumentValue $call.args '--rules'
        Assert-Aw -Condition ($call.args -contains '--rules' -and $grokRules.Contains('src/grok-fake.txt', [System.StringComparison]::Ordinal)) -Message 'GROK_ALLOWLIST_RULE_MISSING'
        Assert-Aw -Condition ($grokRules.Contains('"tests":["string"]', [System.StringComparison]::Ordinal) -and $grokRules.Contains('Never return a scalar string', [System.StringComparison]::Ordinal)) -Message 'GROK_FINAL_ARRAY_SCHEMA_RULE_MISSING'
        Assert-Aw -Condition ($result.StdErr.Contains('FAKE_GROK_PROGRESS_BEFORE_FINAL_REPORT', [System.StringComparison]::Ordinal)) -Message 'GROK_PROGRESS_CHANNEL'
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition ([string]$report.status -eq 'COMPLETE') -Message 'GROK_REPORT'
        Assert-Aw -Condition ([System.IO.File]::ReadAllText((Join-Path $script:Repository 'src\grok-fake.txt'), $script:Utf8) -eq 'grok writer') -Message 'GROK_WRITE_MISSING'
        Assert-Aw -Condition ([System.IO.File]::ReadAllText($script:DirtyWipPath, $script:Utf8) -eq 'existing dirty WIP') -Message 'GROK_DIRTY_WIP_CHANGED'
        $promptPath = Get-AwArgumentValue $call.args '--prompt-file'
        Assert-Aw -Condition (-not [System.IO.Directory]::Exists([System.IO.Path]::GetDirectoryName($promptPath))) -Message 'GROK_TEMP_RESIDUE'
    }

    Invoke-AwCase 'GrokAuthFileWriterOneTask' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'default' -XaiApiKey '' -GrokHome $script:GrokAuthHome
        Assert-Aw -Condition ($result.ExitCode -eq 0) -Message ('GROK_AUTH_FILE_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'GROK_AUTH_FILE_TASK_COUNT'
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq $beforePreflight) -Message 'GROK_AUTH_FILE_UNEXPECTED_PREFLIGHT_PROCESS'
        $call = Read-AwLastTaskCall
        Assert-Aw -Condition ([string]::IsNullOrEmpty([string]$call.env.xai)) -Message 'GROK_AUTH_FILE_XAI_NOT_EMPTY'
        Assert-Aw -Condition ([string]$call.env.grokHome -eq $script:GrokAuthHome) -Message 'GROK_AUTH_FILE_HOME'
    }

    Invoke-AwCase 'GrokAuthMissingStartsNoTask' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $missingHome = Join-Path $script:TestRoot 'missing-grok-home'
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'default' -XaiApiKey '' -GrokHome $missingHome
        Assert-Aw -Condition ($result.ExitCode -eq 65) -Message ('GROK_AUTH_MISSING_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq $beforeTask) -Message 'GROK_TASK_STARTED_AFTER_AUTH_FAILURE'
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq $beforePreflight) -Message 'GROK_AUTH_SHOULD_BE_LOCAL_ONLY'
        Assert-Aw -Condition ($result.StdErr.Contains('AUTH_GUIDANCE=grok login or set XAI_API_KEY', [System.StringComparison]::Ordinal)) -Message 'GROK_AUTH_GUIDANCE_MISSING'
    }

    Invoke-AwCase 'GrokBlockedIsNonzero' {
        $beforeTask = Get-AwTaskCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'blocked'
        Assert-Aw -Condition ($result.ExitCode -eq 11) -Message ('GROK_BLOCKED_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'GROK_BLOCKED_TASK_COUNT'
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition ([string]$report.status -eq 'BLOCKED') -Message 'GROK_BLOCKED_REPORT'
    }

    Invoke-AwCase 'GrokReportTypeRejected' {
        $beforeTask = Get-AwTaskCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'grok_bad_shape'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('GROK_BAD_SHAPE_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'GROK_BAD_SHAPE_TASK_COUNT'
        Assert-Aw -Condition ($result.StdErr.Contains('WRAPPER_ERROR=GROK_REPORT_TESTS_TYPE_INVALID', [System.StringComparison]::Ordinal)) -Message 'GROK_BAD_SHAPE_ERROR'
    }

    foreach ($case in @(
        @{ Name = 'GrokArrayReportRejected'; Scenario = 'grok_array_report'; Error = 'GROK_REPORT_TYPE_INVALID' },
        @{ Name = 'GrokArrayEnvelopeRejected'; Scenario = 'grok_array_envelope'; Error = 'GROK_ENVELOPE_TYPE_INVALID' },
        @{ Name = 'GrokExtraFieldRejected'; Scenario = 'grok_extra_field'; Error = 'GROK_REPORT_FIELD_UNEXPECTED_EXTRA' },
        @{ Name = 'GrokLowercaseStatusRejected'; Scenario = 'grok_lowercase_status'; Error = 'GROK_REPORT_STATUS_INVALID' }
    )) {
        $caseName = [string]$case.Name
        $scenario = [string]$case.Scenario
        $expectedError = [string]$case.Error
        Invoke-AwCase $caseName {
            $beforeTask = Get-AwTaskCallCount
            $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario $scenario
            Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ($caseName + '_EXIT_' + $result.ExitCode)
            Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message ($caseName + '_TASK_COUNT')
            Assert-Aw -Condition ($result.StdErr.Contains($expectedError, [System.StringComparison]::Ordinal)) -Message ($caseName + '_ERROR_MISSING_' + $result.StdErr)
        }
    }

    foreach ($case in @(
        @{ Name = 'GrokDuplicateStatusRejected'; Scenario = 'grok_duplicate_status'; Error = 'GROK_REPORT_DUPLICATE_PROPERTY' },
        @{ Name = 'GrokDuplicateChangedPathsRejected'; Scenario = 'grok_duplicate_changed_paths'; Error = 'GROK_REPORT_DUPLICATE_PROPERTY' },
        @{ Name = 'GrokDuplicateEnvelopeKeyRejected'; Scenario = 'grok_duplicate_envelope_key'; Error = 'GROK_ENVELOPE_DUPLICATE_PROPERTY' }
    )) {
        $caseName = [string]$case.Name
        $scenario = [string]$case.Scenario
        $expectedError = [string]$case.Error
        Invoke-AwCase $caseName {
            $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario $scenario
            Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ($caseName + '_EXIT_' + $result.ExitCode)
            Assert-Aw -Condition ($result.StdErr.Contains($expectedError, [System.StringComparison]::Ordinal)) -Message ($caseName + '_ERROR_MISSING')
        }
    }

    Invoke-AwCase 'GrokOutOfScopeMutationRejectedPreserved' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'grok_out_of_scope'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('GROK_OUT_OF_SCOPE_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ($result.StdErr.Contains('GROK_CHANGE_OUTSIDE_ALLOWLIST', [System.StringComparison]::Ordinal)) -Message 'GROK_OUT_OF_SCOPE_ERROR'
        Assert-Aw -Condition ([System.IO.File]::Exists((Join-Path $script:Repository 'src\forbidden.txt'))) -Message 'GROK_OUT_OF_SCOPE_CHANGE_NOT_PRESERVED'
    }

    Invoke-AwCase 'GrokExistingFileCannotBecomeAllowedDirectory' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'grok_replace_allowed_file_with_directory' `
            -ExtraArguments @('-WriteAllowPath', 'scope-file.txt')
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('GROK_FILE_SCOPE_ESCAPE_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
        Assert-Aw -Condition ($result.StdErr.Contains('GROK_CHANGE_OUTSIDE_ALLOWLIST', [System.StringComparison]::Ordinal)) -Message 'GROK_FILE_SCOPE_ESCAPE_ERROR'
        Assert-Aw -Condition ([System.IO.File]::Exists((Join-Path $script:Repository 'scope-file.txt\child.txt'))) -Message 'GROK_FILE_SCOPE_ESCAPE_NOT_PRESERVED'
    }

    Invoke-AwCase 'GrokReportedActualMismatchRejected' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'grok_report_mismatch'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('GROK_REPORT_MISMATCH_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ($result.StdErr.Contains('GROK_REPORTED_CHANGED_PATHS_MISMATCH', [System.StringComparison]::Ordinal)) -Message 'GROK_REPORT_MISMATCH_ERROR'
    }

    Invoke-AwCase 'GrokFalseCompleteRejected' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'grok_false_complete'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('GROK_FALSE_COMPLETE_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ($result.StdErr.Contains('GROK_REPORTED_CHANGED_PATHS_MISMATCH', [System.StringComparison]::Ordinal)) -Message 'GROK_FALSE_COMPLETE_ERROR'
    }

    Invoke-AwCase 'GrokPreexistingDirtyByteChangeDetectedAndReported' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'grok_modify_dirty_wip' `
            -ExtraArguments @('-WriteAllowPath', 'dirty-wip.txt')
        Assert-Aw -Condition ($result.ExitCode -eq 0) -Message ('GROK_DIRTY_CHANGE_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition (@($report.changed_paths).Count -eq 1 -and [string]$report.changed_paths[0] -eq 'dirty-wip.txt') -Message 'GROK_DIRTY_CHANGE_REPORT'
        Assert-Aw -Condition ([System.IO.File]::ReadAllText($script:DirtyWipPath, $script:Utf8) -eq 'grok writer') -Message 'GROK_DIRTY_CHANGE_BYTES'
    }

    Invoke-AwCase 'GrokIgnoredMutationFailsClosed' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'grok_ignored_change' `
            -ExtraArguments @('-WriteAllowPath', 'ignored-output.tmp')
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('GROK_IGNORED_CHANGE_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ($result.StdErr.Contains('GROK_WATCHER_CHANGE_NOT_IN_FINGERPRINT', [System.StringComparison]::Ordinal)) -Message 'GROK_IGNORED_CHANGE_ERROR'
    }

    Invoke-AwCase 'GrokEmptyDirectoryOnlyMutationRejected' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'grok_empty_dir_only' `
            -ExtraArguments @('-WriteAllowPath', 'scratch-empty')
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('GROK_EMPTY_DIR_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ($result.StdErr.Contains('GROK_WATCHER_CHANGE_NOT_IN_FINGERPRINT', [System.StringComparison]::Ordinal)) -Message 'GROK_EMPTY_DIR_ERROR'
    }

    Invoke-AwCase 'GrokDeletedParentEventRepresentedByChildDelta' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'grok_delete_parent' `
            -ExtraArguments @('-WriteAllowPath', 'delete-tree')
        Assert-Aw -Condition ($result.ExitCode -eq 0) -Message ('GROK_DELETE_PARENT_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition (@($report.changed_paths).Count -eq 1 -and [string]$report.changed_paths[0] -eq 'delete-tree/child.txt') -Message 'GROK_DELETE_PARENT_REPORT'
        Assert-Aw -Condition (-not [System.IO.Directory]::Exists((Join-Path $script:Repository 'delete-tree'))) -Message 'GROK_DELETE_PARENT_SURVIVED'
    }

    Invoke-AwCase 'GrokMutationBeforeNonzeroOverridesChildExit' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'mutation_nonzero'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('GROK_MUTATION_NONZERO_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ($result.StdErr.Contains('GROK_MUTATION_WITHOUT_VALID_REPORT', [System.StringComparison]::Ordinal)) -Message 'GROK_MUTATION_NONZERO_ERROR'
        Assert-Aw -Condition ([System.IO.File]::Exists((Join-Path $script:Repository 'src\grok-fake.txt'))) -Message 'GROK_MUTATION_NONZERO_NOT_PRESERVED'
    }

    Invoke-AwCase 'GrokCancelledReportRejected' {
        $beforeTask = Get-AwTaskCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'grok_cancelled_report'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('GROK_CANCELLED_REPORT_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'GROK_CANCELLED_REPORT_TASK_COUNT'
        Assert-Aw -Condition ($result.StdErr.Contains('GROK_RUN_INCOMPLETE_CANCELLED', [System.StringComparison]::Ordinal)) -Message 'GROK_CANCELLED_REPORT_REASON'
    }

    Invoke-AwCase 'GrokMissingStopReasonRejected' {
        $beforeTask = Get-AwTaskCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'grok_missing_stop_reason'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('GROK_MISSING_STOP_REASON_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'GROK_MISSING_STOP_REASON_TASK_COUNT'
        Assert-Aw -Condition ($result.StdErr.Contains('GROK_STOP_REASON_MISSING', [System.StringComparison]::Ordinal)) -Message 'GROK_MISSING_STOP_REASON_ERROR'
    }

    Invoke-AwCase 'GrokBraceHeavyTrailingReport' {
        $beforeTask = Get-AwTaskCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'grok_brace_heavy'
        Assert-Aw -Condition ($result.ExitCode -eq 0) -Message ('GROK_BRACE_HEAVY_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'GROK_BRACE_HEAVY_TASK_COUNT'
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition ([string]$report.summary -eq ('{' * 80)) -Message 'GROK_BRACE_HEAVY_REPORT'
    }

    Invoke-AwCase 'OpusReviewPassOneCall' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-opus.ps1' -Scenario 'default'
        Assert-Aw -Condition ($result.ExitCode -eq 0) -Message ('OPUS_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'OPUS_TASK_COUNT'
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'OPUS_PREFLIGHT_COUNT'
        $call = Read-AwLastTaskCall
        $preflight = Read-AwLastPreflightCall
        Assert-Aw -Condition ([string]$preflight.provider -eq 'fake-opus' -and $preflight.args[0] -eq 'auth' -and $preflight.args[1] -eq 'status' -and $preflight.args[2] -eq '--json') -Message 'OPUS_PREFLIGHT_ARGS'
        Assert-Aw -Condition ([string]$preflight.env.anthropic -eq 'ANTHROPIC_CANARY' -and $null -eq $preflight.env.openai -and $null -eq $preflight.env.xai -and $null -eq $preflight.env.unrelatedSecret) -Message 'OPUS_PREFLIGHT_ENV_ISOLATION'
        Assert-Aw -Condition ([string]$preflight.env.disable1m -eq '1' -and [string]$preflight.env.disableThinking -eq '1') -Message 'OPUS_PREFLIGHT_COST_CONTROLS'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '--model' 'claude-opus-4-6') -Message 'OPUS_MODEL'
        Assert-Aw -Condition (-not ($call.args -contains 'claude-opus-4-6[1m]')) -Message 'OPUS_1M_MODEL_PRESENT'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '--effort' 'max') -Message 'OPUS_EFFORT'
        Assert-Aw -Condition (-not ($call.args -contains '--settings')) -Message 'OPUS_THINKING_SETTINGS_PRESENT'
        Assert-Aw -Condition ([string]$call.env.disable1m -eq '1' -and [string]$call.env.disableThinking -eq '1') -Message 'OPUS_COST_CONTROLS'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '--permission-mode' 'plan') -Message 'OPUS_PERMISSION'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '--tools' 'Read,Glob,Grep') -Message 'OPUS_TOOLS'
        Assert-Aw -Condition ((Get-AwArgumentValue $call.args '--disallowedTools').Split(',') -contains 'Agent') -Message 'OPUS_AGENT_NOT_DENIED'
        Assert-Aw -Condition ($call.args -contains '--print') -Message 'OPUS_PRINT_MODE_MISSING'
        Assert-Aw -Condition ($call.args -contains '--safe-mode') -Message 'OPUS_SAFE_MODE_MISSING'
        Assert-Aw -Condition ($call.args -contains '--no-chrome') -Message 'OPUS_CHROME_NOT_DISABLED'
        Assert-Aw -Condition ($call.args -contains '--no-session-persistence') -Message 'OPUS_SESSION_PERSISTENCE_NOT_DISABLED'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '--output-format' 'json') -Message 'OPUS_OUTPUT_FORMAT'
        Assert-Aw -Condition (-not ($call.args -contains '--json-schema')) -Message 'OPUS_JSON_SCHEMA_RETRY_SURFACE_PRESENT'
        Assert-Aw -Condition (-not ($call.args -contains '--fallback-model') -and -not ($call.args -contains '--continue') -and -not ($call.args -contains '--resume')) -Message 'OPUS_RETRY_OR_RESUME_SURFACE_PRESENT'
        Assert-Aw -Condition (-not ($call.args -contains '오프라인 계약 검증 task & 100%')) -Message 'OPUS_PROMPT_IN_ARGV'
        Assert-Aw -Condition ($null -eq $call.env.openai -and $null -eq $call.env.xai -and $null -eq $call.env.grok) -Message 'OPUS_CROSS_PROVIDER_SECRET'
        Assert-Aw -Condition ([string]$call.env.anthropic -eq 'ANTHROPIC_CANARY') -Message 'OPUS_OWN_SECRET_REMOVED'
        Assert-Aw -Condition ($null -eq $call.env.unrelatedSecret -and $null -eq $call.env.githubToken -and $null -eq $call.env.awsKey -and $null -eq $call.env.databaseUrl -and $null -eq $call.env.githubPat -and $null -eq $call.env.slackWebhook) -Message 'OPUS_GENERIC_SECRET_LEAK'
        Assert-Aw -Condition ([string]$call.env.claudeHome -eq 'CLAUDE_HOME_CANARY' -and $null -eq $call.env.codexHome -and $null -eq $call.env.grokHome) -Message 'OPUS_PROVIDER_HOME_ISOLATION'
        Assert-Aw -Condition (-not [string]::IsNullOrWhiteSpace([string]$call.env.path) -and -not [string]::IsNullOrWhiteSpace([string]$call.env.systemRoot) -and -not [string]::IsNullOrWhiteSpace([string]$call.env.userProfile)) -Message 'OPUS_REQUIRED_OS_ENV_MISSING'
        $expectedChildTemp = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Temp'))
        Assert-Aw -Condition ([string]$call.env.temp -eq $expectedChildTemp -and [string]$call.env.tmp -eq $expectedChildTemp -and $null -eq $call.env.psModulePath) -Message 'OPUS_CHILD_ENV_BOUNDARY'
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition ([string]$report.verdict -eq 'PASS') -Message 'OPUS_REPORT'
        Assert-Aw -Condition ([System.IO.File]::ReadAllText($script:DirtyWipPath, $script:Utf8) -eq 'existing dirty WIP') -Message 'OPUS_DIRTY_WIP_CHANGED'
        Assert-Aw -Condition (-not (($result.StdOut + $result.StdErr).Contains('AUTH_PREFLIGHT_SECRET_CANARY', [System.StringComparison]::Ordinal))) -Message 'OPUS_AUTH_OUTPUT_LEAKED'
    }

    Invoke-AwCase 'OpusAuthFailureRedactedStartsNoTask' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-opus.ps1' -Scenario 'default' -AuthScenario 'auth_fail'
        Assert-Aw -Condition ($result.ExitCode -eq 65) -Message ('OPUS_AUTH_FAIL_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'OPUS_AUTH_FAIL_PREFLIGHT_COUNT'
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq $beforeTask) -Message 'OPUS_TASK_STARTED_AFTER_AUTH_FAIL'
        Assert-Aw -Condition (-not (($result.StdOut + $result.StdErr).Contains('AUTH_PREFLIGHT_SECRET_CANARY', [System.StringComparison]::Ordinal))) -Message 'OPUS_AUTH_FAILURE_OUTPUT_LEAKED'
        Assert-Aw -Condition ($result.StdErr.Contains('AUTH_GUIDANCE=claude auth login', [System.StringComparison]::Ordinal)) -Message 'OPUS_AUTH_GUIDANCE_MISSING'
    }

    Invoke-AwCase 'OpusFailIsNonzero' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-opus.ps1' -Scenario 'opus_fail'
        Assert-Aw -Condition ($result.ExitCode -eq 10) -Message ('OPUS_FAIL_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'OPUS_FAIL_TASK_COUNT'
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'OPUS_FAIL_PREFLIGHT_COUNT'
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition ([string]$report.verdict -eq 'FAIL') -Message 'OPUS_FAIL_REPORT'
    }

    Invoke-AwCase 'OpusBlockedIsNonzero' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-opus.ps1' -Scenario 'blocked'
        Assert-Aw -Condition ($result.ExitCode -eq 11) -Message ('OPUS_BLOCKED_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'OPUS_BLOCKED_TASK_COUNT'
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'OPUS_BLOCKED_PREFLIGHT_COUNT'
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition ([string]$report.verdict -eq 'BLOCKED') -Message 'OPUS_BLOCKED_REPORT'
    }

    Invoke-AwCase 'OpusReadOnlyMutationRejectedPreserved' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-opus.ps1' -Scenario 'opus_mutates'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('OPUS_MUTATION_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ($result.StdErr.Contains('OPUS_READ_ONLY_REPOSITORY_MUTATED', [System.StringComparison]::Ordinal)) -Message 'OPUS_MUTATION_ERROR'
        Assert-Aw -Condition ([System.IO.File]::Exists((Join-Path $script:Repository 'src\opus-mutated.txt'))) -Message 'OPUS_MUTATION_NOT_PRESERVED'
        Assert-Aw -Condition ([string]::IsNullOrWhiteSpace($result.StdOut)) -Message 'OPUS_FALSE_PASS_EMITTED_AFTER_MUTATION'
    }

    Invoke-AwCase 'OpusMutationBeforeNonzeroOverridesChildExit' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-opus.ps1' -Scenario 'mutation_nonzero'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('OPUS_MUTATION_NONZERO_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ($result.StdErr.Contains('OPUS_READ_ONLY_REPOSITORY_MUTATED', [System.StringComparison]::Ordinal)) -Message 'OPUS_MUTATION_NONZERO_ERROR'
    }

    foreach ($case in @(
        @{ Name = 'OpusErrorEnvelopeRejected'; Scenario = 'opus_error_envelope' },
        @{ Name = 'OpusMissingResultRejected'; Scenario = 'opus_missing_result' },
        @{ Name = 'OpusIncompleteTerminalRejected'; Scenario = 'opus_incomplete_terminal' },
        @{ Name = 'OpusReportTypeRejected'; Scenario = 'opus_bad_shape' },
        @{ Name = 'OpusArrayTypeRejected'; Scenario = 'opus_bad_array' },
        @{ Name = 'OpusFindingTypeRejected'; Scenario = 'opus_bad_finding' },
        @{ Name = 'OpusExtraFieldRejected'; Scenario = 'opus_extra_field' },
        @{ Name = 'OpusProseReportRejected'; Scenario = 'opus_prose_report' },
        @{ Name = 'OpusArrayReportRejected'; Scenario = 'opus_array_report' },
        @{ Name = 'OpusArrayEnvelopeRejected'; Scenario = 'opus_array_envelope' },
        @{ Name = 'OpusInvalidEnvelopeRejected'; Scenario = 'opus_invalid_envelope' }
    )) {
        $caseName = [string]$case.Name
        $scenario = [string]$case.Scenario
        Invoke-AwCase $caseName {
            $beforeTask = Get-AwTaskCallCount
            $beforePreflight = Get-AwPreflightCallCount
            $result = Invoke-AwWrapperProcess -ScriptName 'invoke-opus.ps1' -Scenario $scenario
            Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ($caseName + '_EXIT_' + $result.ExitCode)
            Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message ($caseName + '_TASK_COUNT')
            Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message ($caseName + '_PREFLIGHT_COUNT')
            Assert-Aw -Condition ($result.StdErr.Contains('WRAPPER_ERROR=OPUS_', [System.StringComparison]::Ordinal)) -Message ($caseName + '_ERROR_MISSING')
        }
    }

    Invoke-AwCase 'CodexDefaultReviewGrade3OneCall' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default'
        Assert-Aw -Condition ($result.ExitCode -eq 0) -Message ('CODEX_REVIEW_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'CODEX_REVIEW_TASK_COUNT'
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'CODEX_REVIEW_PREFLIGHT_COUNT'
        $call = Read-AwLastTaskCall
        $preflight = Read-AwLastPreflightCall
        Assert-Aw -Condition ([string]$preflight.provider -eq 'fake-codex' -and $preflight.args[0] -eq 'login' -and $preflight.args[1] -eq 'status') -Message 'CODEX_PREFLIGHT_ARGS'
        Assert-Aw -Condition ([string]$preflight.env.openai -eq 'OPENAI_CANARY' -and $null -eq $preflight.env.anthropic -and $null -eq $preflight.env.xai -and $null -eq $preflight.env.unrelatedSecret) -Message 'CODEX_PREFLIGHT_ENV_ISOLATION'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '--model' 'gpt-5.6-sol') -Message 'CODEX_MODEL'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '--sandbox' 'read-only') -Message 'CODEX_REVIEW_SANDBOX'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '-c' 'model_reasoning_effort="xhigh"') -Message 'CODEX_EFFORT'
        Assert-Aw -Condition (-not (Test-AwArgumentPair $call.args '-c' 'service_tier="fast"') -and -not (Test-AwArgumentPair $call.args '--enable' 'fast_mode')) -Message 'CODEX_REVIEW_FAST_MODE'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '-c' 'sandbox_workspace_write.network_access=false') -Message 'CODEX_REVIEW_NETWORK_POLICY'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '-c' 'windows.sandbox="elevated"') -Message 'CODEX_WINDOWS_SANDBOX'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '-c' 'features.multi_agent=false') -Message 'CODEX_MULTI_AGENT_NOT_DISABLED'
        Assert-Aw -Condition ($call.stdin.Contains('Do not report BLOCKED while an in-scope read-only method remains.', [System.StringComparison]::Ordinal)) -Message 'CODEX_READ_ONLY_ALTERNATIVE_GUIDANCE_MISSING'
        Assert-Aw -Condition (-not ($call.args -contains 'allow_login_shell=false')) -Message 'CODEX_LOGIN_SHELL_BLOCK_PRESENT'
        Assert-Aw -Condition (-not ($call.args -contains '오프라인 계약 검증 task & 100%')) -Message 'CODEX_PROMPT_IN_ARGV'
        Assert-Aw -Condition ($null -eq $call.env.anthropic -and $null -eq $call.env.xai -and $null -eq $call.env.grok) -Message 'CODEX_CROSS_PROVIDER_SECRET'
        Assert-Aw -Condition ([string]$call.env.openai -eq 'OPENAI_CANARY') -Message 'CODEX_OWN_SECRET_REMOVED'
        Assert-Aw -Condition ($null -eq $call.env.unrelatedSecret -and $null -eq $call.env.githubToken -and $null -eq $call.env.awsKey -and $null -eq $call.env.databaseUrl -and $null -eq $call.env.githubPat -and $null -eq $call.env.slackWebhook) -Message 'CODEX_GENERIC_SECRET_LEAK'
        Assert-Aw -Condition ([string]$call.env.codexHome -eq 'CODEX_HOME_CANARY' -and $null -eq $call.env.claudeHome -and $null -eq $call.env.grokHome) -Message 'CODEX_PROVIDER_HOME_ISOLATION'
        Assert-Aw -Condition (-not [string]::IsNullOrWhiteSpace([string]$call.env.path) -and -not [string]::IsNullOrWhiteSpace([string]$call.env.systemRoot) -and -not [string]::IsNullOrWhiteSpace([string]$call.env.userProfile)) -Message 'CODEX_REQUIRED_OS_ENV_MISSING'
        $expectedChildTemp = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Temp'))
        Assert-Aw -Condition ([string]$call.env.temp -eq $expectedChildTemp -and [string]$call.env.tmp -eq $expectedChildTemp -and $null -eq $call.env.psModulePath) -Message 'CODEX_CHILD_ENV_BOUNDARY'
        Assert-Aw -Condition ([string]$call.env.gitOptionalLocks -eq '0' -and [string]$call.env.gitTerminalPrompt -eq '0' -and [string]$call.env.gcmInteractive -eq 'never') -Message 'CODEX_GIT_LOCK_AND_PROMPT_GUARD_MISSING'
        Assert-Aw -Condition ($result.StdErr.Contains('kind=review grade=3 model=gpt-5.6-sol effort=xhigh fast=off', [System.StringComparison]::Ordinal)) -Message 'CODEX_REVIEW_GRADE_LOG_MISSING'
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition ([string]$report.mode -eq 'review' -and [string]$report.verdict -eq 'PASS') -Message 'CODEX_REVIEW_REPORT'
        Assert-Aw -Condition (-not [System.IO.File]::Exists((Join-Path $script:Repository 'src\codex-fake.txt'))) -Message 'CODEX_REVIEW_WROTE_FILE'
        Assert-Aw -Condition ([System.IO.File]::ReadAllText($script:DirtyWipPath, $script:Utf8) -eq 'existing dirty WIP') -Message 'CODEX_REVIEW_DIRTY_WIP_CHANGED'
        Assert-Aw -Condition (-not (($result.StdOut + $result.StdErr).Contains('AUTH_PREFLIGHT_SECRET_CANARY', [System.StringComparison]::Ordinal))) -Message 'CODEX_AUTH_OUTPUT_LEAKED'
        $finalPath = Get-AwArgumentValue $call.args '--output-last-message'
        Assert-Aw -Condition (-not [System.IO.Directory]::Exists([System.IO.Path]::GetDirectoryName($finalPath))) -Message 'CODEX_TEMP_RESIDUE'
    }

    foreach ($case in @(
        @{ Name = 'CodexReviewGrade1'; Grade = 1; Model = 'gpt-5.6-luna'; Effort = 'max'; HasFast = $true },
        @{ Name = 'CodexReviewGrade2'; Grade = 2; Model = 'gpt-5.6-luna'; Effort = 'max'; HasFast = $true },
        @{ Name = 'CodexReviewGrade3'; Grade = 3; Model = 'gpt-5.6-sol'; Effort = 'xhigh'; HasFast = $false },
        @{ Name = 'CodexReviewGrade4'; Grade = 4; Model = 'gpt-5.6-sol'; Effort = 'xhigh'; HasFast = $false },
        @{ Name = 'CodexReviewGrade5'; Grade = 5; Model = 'gpt-5.6-sol'; Effort = 'ultra'; HasFast = $false }
    )) {
        $caseName = [string]$case.Name
        $grade = [int]$case.Grade
        $model = [string]$case.Model
        $effort = [string]$case.Effort
        $hasFast = [bool]$case.HasFast
        Invoke-AwCase $caseName {
            $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default' `
                -ExtraArguments @('-ReviewGrade', [string]$grade)
            Assert-Aw -Condition ($result.ExitCode -eq 0) -Message ($caseName + '_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
            $call = Read-AwLastTaskCall
            Assert-Aw -Condition (Test-AwArgumentPair $call.args '--model' $model) -Message ($caseName + '_MODEL')
            Assert-Aw -Condition (Test-AwArgumentPair $call.args '-c' ('model_reasoning_effort="{0}"' -f $effort)) -Message ($caseName + '_EFFORT')
            $hasServiceTier = Test-AwArgumentPair $call.args '-c' 'service_tier="fast"'
            $hasFastEnable = Test-AwArgumentPair $call.args '--enable' 'fast_mode'
            Assert-Aw -Condition ($hasServiceTier -eq $hasFast -and $hasFastEnable -eq $hasFast) -Message ($caseName + '_FAST_MODE')
            Assert-Aw -Condition (Test-AwArgumentPair $call.args '--sandbox' 'read-only') -Message ($caseName + '_SANDBOX')
            Assert-Aw -Condition (Test-AwArgumentPair $call.args '-c' 'sandbox_workspace_write.network_access=false') -Message ($caseName + '_NETWORK')
            Assert-Aw -Condition ($call.stdin.Contains(('review grade {0}' -f $grade), [System.StringComparison]::Ordinal)) -Message ($caseName + '_PROMPT_GRADE')
        }
    }

    Invoke-AwCase 'CodexAuthFailureRedactedStartsNoTask' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default' -AuthScenario 'auth_fail'
        Assert-Aw -Condition ($result.ExitCode -eq 65) -Message ('CODEX_AUTH_FAIL_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'CODEX_AUTH_FAIL_PREFLIGHT_COUNT'
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq $beforeTask) -Message 'CODEX_TASK_STARTED_AFTER_AUTH_FAIL'
        Assert-Aw -Condition (-not (($result.StdOut + $result.StdErr).Contains('AUTH_PREFLIGHT_SECRET_CANARY', [System.StringComparison]::Ordinal))) -Message 'CODEX_AUTH_FAILURE_OUTPUT_LEAKED'
        Assert-Aw -Condition ($result.StdErr.Contains('AUTH_GUIDANCE=codex login', [System.StringComparison]::Ordinal)) -Message 'CODEX_AUTH_GUIDANCE_MISSING'
    }

    Invoke-AwCase 'CodexAuthMutationRejectedBeforeTask' {
        $beforeTask = Get-AwTaskCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default' -AuthScenario 'auth_mutates_repository'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('CODEX_AUTH_MUTATION_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq $beforeTask) -Message 'CODEX_TASK_STARTED_AFTER_AUTH_MUTATION'
        Assert-Aw -Condition ($result.StdErr.Contains('CODEX_READ_ONLY_REPOSITORY_MUTATED', [System.StringComparison]::Ordinal)) -Message 'CODEX_AUTH_MUTATION_ERROR'
        Assert-Aw -Condition ([System.IO.File]::Exists((Join-Path $script:Repository 'src\auth-mutated.txt'))) -Message 'CODEX_AUTH_MUTATION_NOT_PRESERVED'
    }

    foreach ($authMutationCase in @(
        @{ Name = 'CodexAuthIgnoredMutationRejectedBeforeTask'; Scenario = 'auth_mutates_ignored' },
        @{ Name = 'CodexAuthTransientMutationRejectedBeforeTask'; Scenario = 'auth_mutates_then_restores' }
    )) {
        $caseName = [string]$authMutationCase.Name
        $authScenario = [string]$authMutationCase.Scenario
        Invoke-AwCase $caseName {
            $beforeTask = Get-AwTaskCallCount
            $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default' -AuthScenario $authScenario
            Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ($caseName + '_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
            Assert-Aw -Condition ((Get-AwTaskCallCount) -eq $beforeTask) -Message ($caseName + '_TASK_STARTED')
            Assert-Aw -Condition ($result.StdErr.Contains('CODEX_READ_ONLY_REPOSITORY_MUTATED', [System.StringComparison]::Ordinal)) -Message ($caseName + '_ERROR')
        }
    }

    Invoke-AwCase 'CodexReviewFailIsNonzero' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'codex_fail'
        Assert-Aw -Condition ($result.ExitCode -eq 10) -Message ('CODEX_FAIL_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'CODEX_FAIL_TASK_COUNT'
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'CODEX_FAIL_PREFLIGHT_COUNT'
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition ([string]$report.mode -eq 'review' -and [string]$report.verdict -eq 'FAIL') -Message 'CODEX_FAIL_REPORT'
    }

    Invoke-AwCase 'CodexBlockedIsNonzero' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'blocked'
        Assert-Aw -Condition ($result.ExitCode -eq 11) -Message ('CODEX_BLOCKED_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'CODEX_BLOCKED_TASK_COUNT'
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'CODEX_BLOCKED_PREFLIGHT_COUNT'
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition ([string]$report.status -eq 'BLOCKED' -and [string]$report.verdict -eq 'NOT_APPLICABLE') -Message 'CODEX_BLOCKED_REPORT'
    }

    Invoke-AwCase 'CodexReadOnlyMutationRejectedPreserved' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'codex_mutates'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('CODEX_MUTATION_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ($result.StdErr.Contains('CODEX_READ_ONLY_REPOSITORY_MUTATED', [System.StringComparison]::Ordinal)) -Message 'CODEX_MUTATION_ERROR'
        Assert-Aw -Condition ($result.StdErr.Contains('REPOSITORY_GUARD provider=CODEX', [System.StringComparison]::Ordinal) -and $result.StdErr.Contains('REPOSITORY_GUARD_WATCHER_PATHS=', [System.StringComparison]::Ordinal)) -Message 'CODEX_MUTATION_PATH_DIAGNOSTIC_MISSING'
        Assert-Aw -Condition ($result.StdErr.Contains('CODEX_CHILD_DIAGNOSTICS_BEGIN', [System.StringComparison]::Ordinal) -and $result.StdErr.Contains('CODEX_CHILD_STDOUT_BEGIN', [System.StringComparison]::Ordinal) -and $result.StdErr.Contains('FAKE_CODEX_PROGRESS', [System.StringComparison]::Ordinal)) -Message 'CODEX_MUTATION_TRANSCRIPT_MISSING'
        Assert-Aw -Condition ($result.StdErr.Contains('CODEX_CHILD_FINAL_JSON_BEGIN', [System.StringComparison]::Ordinal) -and $result.StdErr.Contains('"summary":"fake codex"', [System.StringComparison]::Ordinal)) -Message 'CODEX_MUTATION_FINAL_JSON_MISSING'
        Assert-Aw -Condition ([System.IO.File]::Exists((Join-Path $script:Repository 'src\codex-mutated.txt'))) -Message 'CODEX_MUTATION_NOT_PRESERVED'
        Assert-Aw -Condition ([string]::IsNullOrWhiteSpace($result.StdOut)) -Message 'CODEX_FALSE_PASS_EMITTED_AFTER_MUTATION'
    }

    Invoke-AwCase 'CodexPreexistingDirtyMutationRejected' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'codex_mutates_dirty'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('CODEX_DIRTY_MUTATION_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ($result.StdErr.Contains('CODEX_READ_ONLY_REPOSITORY_MUTATED', [System.StringComparison]::Ordinal)) -Message 'CODEX_DIRTY_MUTATION_ERROR'
        Assert-Aw -Condition ([System.IO.File]::ReadAllText($script:DirtyWipPath, $script:Utf8) -eq 'codex changed dirty WIP') -Message 'CODEX_DIRTY_MUTATION_NOT_PRESERVED'
    }

    Invoke-AwCase 'CodexIgnoredMutationRejectedByWatcher' {
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'codex_mutates_ignored'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('CODEX_IGNORED_MUTATION_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ($result.StdErr.Contains('CODEX_READ_ONLY_REPOSITORY_MUTATED', [System.StringComparison]::Ordinal)) -Message 'CODEX_IGNORED_MUTATION_ERROR'
        Assert-Aw -Condition ([System.IO.File]::Exists($script:IgnoredPath)) -Message 'CODEX_IGNORED_MUTATION_NOT_PRESERVED'
    }

    Invoke-AwCase 'CodexSimpleTestSparkPass' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default' -ExtraArguments @('-SimpleTest')
        Assert-Aw -Condition ($result.ExitCode -eq 0) -Message ('CODEX_SPARK_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'CODEX_SPARK_TASK_COUNT'
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'CODEX_SPARK_PREFLIGHT_COUNT'
        $call = Read-AwLastTaskCall
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '--model' 'gpt-5.3-codex-spark') -Message 'CODEX_SPARK_MODEL'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '--sandbox' 'read-only') -Message 'CODEX_SPARK_SANDBOX'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '-c' 'model_reasoning_effort="xhigh"') -Message 'CODEX_SPARK_EFFORT'
        Assert-Aw -Condition (Test-AwArgumentPair $call.args '-c' 'features.multi_agent=false') -Message 'CODEX_SPARK_MULTI_AGENT_NOT_DISABLED'
        Assert-Aw -Condition ($call.stdin.Contains('Do not report BLOCKED while an in-scope read-only method remains.', [System.StringComparison]::Ordinal)) -Message 'CODEX_SPARK_READ_ONLY_ALTERNATIVE_GUIDANCE_MISSING'
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition ([string]$report.mode -eq 'simple_test' -and [string]$report.verdict -eq 'PASS' -and @($report.changed_paths).Count -eq 0) -Message 'CODEX_SPARK_REPORT'
        Assert-Aw -Condition (-not [System.IO.File]::Exists((Join-Path $script:Repository 'src\codex-fake.txt'))) -Message 'CODEX_SPARK_WROTE_FILE'
        Assert-Aw -Condition ([System.IO.File]::ReadAllText($script:DirtyWipPath, $script:Utf8) -eq 'existing dirty WIP') -Message 'CODEX_SPARK_DIRTY_WIP_CHANGED'
    }

    foreach ($case in @(
        @{ Name = 'CodexTestGrade1'; Grade = 1; Model = 'gpt-5.3-codex-spark'; Effort = 'xhigh'; HasFast = $false; Sandbox = 'read-only'; Network = 'false' },
        @{ Name = 'CodexTestGrade2'; Grade = 2; Model = 'gpt-5.3-codex-spark'; Effort = 'xhigh'; HasFast = $false; Sandbox = 'read-only'; Network = 'false' },
        @{ Name = 'CodexTestGrade3'; Grade = 3; Model = 'gpt-5.6-luna'; Effort = 'max'; HasFast = $true; Sandbox = 'workspace-write'; Network = 'true' },
        @{ Name = 'CodexTestGrade4'; Grade = 4; Model = 'gpt-5.6-luna'; Effort = 'max'; HasFast = $true; Sandbox = 'workspace-write'; Network = 'true' },
        @{ Name = 'CodexTestGrade5'; Grade = 5; Model = 'gpt-5.6-sol'; Effort = 'max'; HasFast = $false; Sandbox = 'workspace-write'; Network = 'true' }
    )) {
        $caseName = [string]$case.Name
        $grade = [int]$case.Grade
        $model = [string]$case.Model
        $effort = [string]$case.Effort
        $hasFast = [bool]$case.HasFast
        $sandbox = [string]$case.Sandbox
        $network = [string]$case.Network
        Invoke-AwCase $caseName {
            $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default' `
                -ExtraArguments @('-TestGrade', [string]$grade)
            Assert-Aw -Condition ($result.ExitCode -eq 0) -Message ($caseName + '_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
            $call = Read-AwLastTaskCall
            Assert-Aw -Condition (Test-AwArgumentPair $call.args '--model' $model) -Message ($caseName + '_MODEL')
            Assert-Aw -Condition (Test-AwArgumentPair $call.args '-c' ('model_reasoning_effort="{0}"' -f $effort)) -Message ($caseName + '_EFFORT')
            Assert-Aw -Condition (Test-AwArgumentPair $call.args '--sandbox' $sandbox) -Message ($caseName + '_SANDBOX')
            Assert-Aw -Condition (Test-AwArgumentPair $call.args '-c' ('sandbox_workspace_write.network_access={0}' -f $network)) -Message ($caseName + '_NETWORK')
            $hasServiceTier = Test-AwArgumentPair $call.args '-c' 'service_tier="fast"'
            $hasFastEnable = Test-AwArgumentPair $call.args '--enable' 'fast_mode'
            Assert-Aw -Condition ($hasServiceTier -eq $hasFast -and $hasFastEnable -eq $hasFast) -Message ($caseName + '_FAST_MODE')
            $report = $result.StdOut | ConvertFrom-Json
            Assert-Aw -Condition ([string]$report.mode -eq ('test_grade_{0}' -f $grade)) -Message ($caseName + '_REPORT_MODE')
            Assert-Aw -Condition ($call.stdin.Contains(('test grade {0}' -f $grade), [System.StringComparison]::Ordinal)) -Message ($caseName + '_PROMPT_GRADE')
        }
    }

    Invoke-AwCase 'CodexGradeRequiredStartsNoNative' {
        $before = Get-AwCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default' -NoDefaultCodexGrade
        Assert-Aw -Condition ($result.ExitCode -eq 64) -Message ('CODEX_GRADE_REQUIRED_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwCallCount) -eq $before) -Message 'CODEX_NATIVE_STARTED_WITHOUT_GRADE'
        Assert-Aw -Condition ($result.StdErr.Contains('WRAPPER_ERROR=CODEX_GRADE_REQUIRED', [System.StringComparison]::Ordinal)) -Message 'CODEX_GRADE_REQUIRED_ERROR'
    }

    Invoke-AwCase 'CodexGradeConflictStartsNoNative' {
        $before = Get-AwCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default' `
            -ExtraArguments @('-TestGrade', '2', '-ReviewGrade', '3')
        Assert-Aw -Condition ($result.ExitCode -eq 64) -Message ('CODEX_GRADE_CONFLICT_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwCallCount) -eq $before) -Message 'CODEX_NATIVE_STARTED_WITH_CONFLICTING_GRADES'
        Assert-Aw -Condition ($result.StdErr.Contains('WRAPPER_ERROR=CODEX_GRADE_CONFLICT', [System.StringComparison]::Ordinal)) -Message 'CODEX_GRADE_CONFLICT_ERROR'
    }

    Invoke-AwCase 'CodexSimpleTestSparkFail' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'codex_fail' -ExtraArguments @('-SimpleTest')
        Assert-Aw -Condition ($result.ExitCode -eq 10) -Message ('CODEX_SPARK_FAIL_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1) -and (Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'CODEX_SPARK_FAIL_COUNTS'
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition ([string]$report.mode -eq 'simple_test' -and [string]$report.verdict -eq 'FAIL') -Message 'CODEX_SPARK_FAIL_REPORT'
    }

    Invoke-AwCase 'CodexSimpleTestSparkBlocked' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'blocked' -ExtraArguments @('-SimpleTest')
        Assert-Aw -Condition ($result.ExitCode -eq 11) -Message ('CODEX_SPARK_BLOCKED_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1) -and (Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'CODEX_SPARK_BLOCKED_COUNTS'
        $report = $result.StdOut | ConvertFrom-Json
        Assert-Aw -Condition ([string]$report.mode -eq 'simple_test' -and [string]$report.status -eq 'BLOCKED' -and [string]$report.verdict -eq 'NOT_APPLICABLE') -Message 'CODEX_SPARK_BLOCKED_REPORT'
    }

    Invoke-AwCase 'CodexImplementArgumentRejectedNoNative' {
        $before = Get-AwCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default' -ExtraArguments @('-Implement')
        Assert-Aw -Condition ($result.ExitCode -ne 0) -Message 'CODEX_IMPLEMENT_ARGUMENT_ACCEPTED'
        Assert-Aw -Condition ((Get-AwCallCount) -eq $before) -Message 'NATIVE_STARTED_FOR_REMOVED_IMPLEMENT_ARGUMENT'
    }

    Invoke-AwCase 'CodexChangedPathsRejected' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'codex_changed_path'
        Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ('CODEX_CHANGED_PATH_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1) -and (Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'CODEX_CHANGED_PATH_COUNTS'
        Assert-Aw -Condition ($result.StdErr.Contains('CODEX_READ_ONLY_REPORTED_CHANGES', [System.StringComparison]::Ordinal)) -Message 'CODEX_CHANGED_PATH_ERROR_MISSING'
    }

    foreach ($case in @(
        @{ Name = 'CodexReportTypeRejected'; Scenario = 'codex_bad_shape' },
        @{ Name = 'CodexArrayTypeRejected'; Scenario = 'codex_bad_array' },
        @{ Name = 'CodexFindingTypeRejected'; Scenario = 'codex_bad_finding' },
        @{ Name = 'CodexExtraFieldRejected'; Scenario = 'codex_extra_field' },
        @{ Name = 'CodexInvalidJsonRejected'; Scenario = 'codex_invalid_json' },
        @{ Name = 'CodexArrayReportRejected'; Scenario = 'codex_array_report' },
        @{ Name = 'CodexMissingReportRejected'; Scenario = 'codex_report_missing' }
    )) {
        $caseName = [string]$case.Name
        $scenario = [string]$case.Scenario
        Invoke-AwCase $caseName {
            $beforeTask = Get-AwTaskCallCount
            $beforePreflight = Get-AwPreflightCallCount
            $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario $scenario
            Assert-Aw -Condition ($result.ExitCode -eq 20) -Message ($caseName + '_EXIT_' + $result.ExitCode)
            Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message ($caseName + '_TASK_COUNT')
            Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message ($caseName + '_PREFLIGHT_COUNT')
            Assert-Aw -Condition ($result.StdErr.Contains('WRAPPER_ERROR=CODEX_', [System.StringComparison]::Ordinal)) -Message ($caseName + '_ERROR_MISSING')
        }
    }

    Invoke-AwCase 'AuthPreflightTimeoutStartsNoTask' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-opus.ps1' -Scenario 'default' -AuthScenario 'auth_timeout' -OuterTimeoutMilliseconds 45000
        Assert-Aw -Condition ($result.ExitCode -eq 65) -Message ('AUTH_TIMEOUT_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'AUTH_TIMEOUT_PREFLIGHT_COUNT'
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq $beforeTask) -Message 'TASK_STARTED_AFTER_AUTH_TIMEOUT'
        $call = Read-AwLastPreflightCall
        Start-Sleep -Milliseconds 100
        Assert-Aw -Condition ($null -eq (Get-Process -Id ([int]$call.pid) -ErrorAction SilentlyContinue)) -Message 'AUTH_TIMEOUT_PROCESS_SURVIVED'
    }

    Invoke-AwCase 'AuthPreflightOutputLimitStartsNoTask' {
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-codex.ps1' -Scenario 'default' -AuthScenario 'auth_output_limit'
        Assert-Aw -Condition ($result.ExitCode -eq 65) -Message ('AUTH_OUTPUT_LIMIT_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
        Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'AUTH_OUTPUT_LIMIT_PREFLIGHT_COUNT'
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq $beforeTask) -Message 'TASK_STARTED_AFTER_AUTH_OUTPUT_LIMIT'
    }

    Invoke-AwCase 'NativeNonzeroPreserved' {
        $beforeTask = Get-AwTaskCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'nonzero'
        Assert-Aw -Condition ($result.ExitCode -eq 73) -Message ('NATIVE_EXIT_' + $result.ExitCode)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'NATIVE_TASK_COUNT'
        Assert-Aw -Condition ($result.StdOut -eq 'FAKE_STDOUT_SENTINEL') -Message 'NATIVE_STDOUT'
        Assert-Aw -Condition ($result.StdErr -eq 'FAKE_STDERR_SENTINEL') -Message 'NATIVE_STDERR'
    }

    Invoke-AwCase 'TimeoutKillsSingleAI' {
        $largePromptPath = Join-Path $script:TestRoot 'large-prompt.txt'
        [System.IO.File]::WriteAllText($largePromptPath, ([string]::new([char]'P', 1048576)), $script:Utf8)
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        try {
            $config.opusTimeoutSeconds = 1
            [System.IO.File]::WriteAllText($script:ConfigPath, ($config | ConvertTo-Json -Depth 20), $script:Utf8)
            $result = Invoke-AwWrapperProcess -ScriptName 'invoke-opus.ps1' -Scenario 'stdin_hang' -PromptFilePath $largePromptPath
            Assert-Aw -Condition ($result.ExitCode -eq 124) -Message ('TIMEOUT_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
            Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'TIMEOUT_TASK_COUNT'
            Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'TIMEOUT_PREFLIGHT_COUNT'
            Assert-Aw -Condition ($result.StdOut.Length -gt 0) -Message 'PARTIAL_UTF8_DIAGNOSTIC_MISSING'
            $call = Read-AwLastTaskCall
            Start-Sleep -Milliseconds 100
            Assert-Aw -Condition ($null -eq (Get-Process -Id ([int]$call.pid) -ErrorAction SilentlyContinue)) -Message 'TIMEOUT_CHILD_SURVIVED'
        }
        finally {
            $config.opusTimeoutSeconds = 5
            [System.IO.File]::WriteAllText($script:ConfigPath, ($config | ConvertTo-Json -Depth 20), $script:Utf8)
        }
    }

    Invoke-AwCase 'RootExitDescendantKilled' {
        if ([System.IO.File]::Exists($script:ChildPidPath)) { [System.IO.File]::Delete($script:ChildPidPath) }
        $beforeTask = Get-AwTaskCallCount
        $beforePreflight = Get-AwPreflightCallCount
        try {
            $config.opusTimeoutSeconds = 1
            [System.IO.File]::WriteAllText($script:ConfigPath, ($config | ConvertTo-Json -Depth 20), $script:Utf8)
            $result = Invoke-AwWrapperProcess -ScriptName 'invoke-opus.ps1' -Scenario 'root_exit_child'
            Assert-Aw -Condition ($result.ExitCode -eq 124) -Message ('DESCENDANT_TIMEOUT_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
            Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'DESCENDANT_ROOT_TASK_COUNT'
            Assert-Aw -Condition ((Get-AwPreflightCallCount) -eq ($beforePreflight + 1)) -Message 'DESCENDANT_ROOT_PREFLIGHT_COUNT'
            Assert-Aw -Condition ([System.IO.File]::Exists($script:ChildPidPath)) -Message 'DESCENDANT_PID_MISSING'
            $childPid = [int][System.IO.File]::ReadAllText($script:ChildPidPath, $script:Utf8)
            Start-Sleep -Milliseconds 100
            Assert-Aw -Condition ($null -eq (Get-Process -Id $childPid -ErrorAction SilentlyContinue)) -Message 'DESCENDANT_SURVIVED'
        }
        finally {
            $config.opusTimeoutSeconds = 5
            [System.IO.File]::WriteAllText($script:ConfigPath, ($config | ConvertTo-Json -Depth 20), $script:Utf8)
        }
    }

    Invoke-AwCase 'OutputLimitKillsSingleAI' {
        $beforeTask = Get-AwTaskCallCount
        $result = Invoke-AwWrapperProcess -ScriptName 'invoke-grok.ps1' -Scenario 'output_limit'
        Assert-Aw -Condition ($result.ExitCode -eq 125) -Message ('OUTPUT_LIMIT_EXIT_' + $result.ExitCode + '_' + $result.StdErr)
        Assert-Aw -Condition ((Get-AwTaskCallCount) -eq ($beforeTask + 1)) -Message 'OUTPUT_LIMIT_TASK_COUNT'
        Assert-Aw -Condition ($result.StdOut.Length -le 65536) -Message 'OUTPUT_CAP_EXCEEDED'
    }
}
finally {
    if ([System.IO.Directory]::Exists($script:ReparseDescendant)) {
        try { [System.IO.Directory]::Delete($script:ReparseDescendant) } catch { }
    }
    $full = [System.IO.Path]::GetFullPath($script:TestRoot)
    $prefix = $tempBase.TrimEnd([char]'\', [char]'/') + [System.IO.Path]::DirectorySeparatorChar
    if ($full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) -and
        [System.IO.Path]::GetFileName($full).StartsWith('ai-wrapper-offline-', [System.StringComparison]::Ordinal)) {
        try { Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop } catch { }
    }
}

foreach ($failure in $script:Failures) { [Console]::Error.WriteLine($failure) }
[Console]::Out.WriteLine(('AI_WRAPPER_OFFLINE total={0} passed={1} failed={2}' -f ($script:Passed + $script:Failed), $script:Passed, $script:Failed))
if ($script:Failed -ne 0) { exit 1 }
