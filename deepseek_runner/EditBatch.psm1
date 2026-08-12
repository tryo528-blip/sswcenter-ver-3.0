# EditBatch.psm1
# Atomic multi-file edit with in-memory preimage rollback.
# Operations: replace | rewrite | create | delete
# Uses hashtables + ArrayList to avoid StrictMode/PSCustomObject property issues.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function New-EditBatch {
    param(
        [Parameter(Mandatory)]$Workspace,
        [long]$MaxBatchBytes = 8MB
    )
    return [PSCustomObject]@{
        Workspace     = $Workspace
        Ops           = [System.Collections.ArrayList]::new()
        Preimages     = @{}
        MaxBatchBytes = $MaxBatchBytes
        Applied       = $false
        Divergent     = [System.Collections.ArrayList]::new()
    }
}

function Add-EditOp {
    param(
        [Parameter(Mandatory)]$Batch,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Op,
        [string]$Context = '',
        [string]$OldText = '',
        [string]$NewText = '',
        [string]$Content = '',
        [string]$ExpectedSha = ''
    )
    if ($Op -notin @('replace','rewrite','create','delete')) {
        throw "TOOL_ARGUMENTS_INVALID: op must be replace|rewrite|create|delete, got '$Op'"
    }
    $null = $Batch.Ops.Add(@{
        Path         = ($Path -replace '\\','/')
        Op           = $Op
        Context      = $Context
        OldText      = $OldText
        NewText      = $NewText
        Content      = $Content
        ExpectedSha  = $ExpectedSha
    })
}

function Test-EditBatchSize {
    param([Parameter(Mandatory)]$Batch)
    $total = 0L
    foreach ($op in $Batch.Ops) {
        foreach ($key in @('Content', 'NewText', 'Context')) {
            $val = $op[$key]
            if ($val) {
                $total += [System.Text.Encoding]::UTF8.GetByteCount([string]$val)
            }
        }
    }
    if ($total -gt $Batch.MaxBatchBytes) {
        throw "BATCH_TOO_LARGE: $total bytes > MaxBatchBytes $($Batch.MaxBatchBytes)"
    }
}

function Get-EditBytesSha256 {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyCollection()]
        [byte[]]$Bytes
    )
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha.ComputeHash($Bytes)
        return ([BitConverter]::ToString($hash) -replace '-','').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function ConvertTo-EditUtf8Bytes {
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Content
    )
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    # Prevent PowerShell's pipeline from unrolling a byte array. In
    # particular, an empty file must remain byte[0] rather than becoming null.
    return ,([byte[]]$utf8NoBom.GetBytes($Content))
}

function Invoke-EditBatch {
    param([Parameter(Mandatory)]$Batch)

    if ($Batch.Ops.Count -eq 0) {
        return @{ ok = $true; results = @(); message = 'empty batch' }
    }

    Test-EditBatchSize -Batch $Batch

    $ws = $Batch.Workspace
    $results = [System.Collections.ArrayList]::new()
    $appliedPaths = [System.Collections.ArrayList]::new()
    $plans = @{}
    $planOrder = [System.Collections.ArrayList]::new()

    # Phase 1: seal the initial state and compose every logical operation in
    # memory. Repeated operations for one normalized path are supported only
    # when every operation is replace. This gives replace calls an evolving
    # buffer while keeping create/rewrite/delete semantics unambiguous.
    try {
        foreach ($op in $Batch.Ops) {
            $resolved = Resolve-WorkspacePath -Workspace $ws -RelativePath $op.Path -Mode Write
            $rel = $resolved.Relative
            $full = $resolved.Full

            if (-not $plans.ContainsKey($rel)) {
                # §7: always seal current existence+SHA as initial BEFORE any mutation.
                $null = Get-OrRecordFileState -Workspace $ws -RelativePath $rel -AsInitial $true -ForceRefresh $true
                $exists = Test-Path -LiteralPath $full -PathType Leaf
                $initialBytes = $null
                $initialSha = $null
                if ($exists) {
                    # Direct assignment preserves byte[0] for an existing empty
                    # file; an if-expression would emit no pipeline object.
                    $initialBytes = [byte[]][System.IO.File]::ReadAllBytes($full)
                    $initialSha = Get-EditBytesSha256 -Bytes $initialBytes
                }
                if ($exists) { $Batch.Preimages[$rel] = $initialBytes }
                $plans[$rel] = @{
                    Relative      = $rel
                    Full          = $full
                    InitialExists = $exists
                    InitialBytes  = $initialBytes
                    InitialSha    = $initialSha
                    WorkingBytes  = $initialBytes
                    FinalContent  = $null
                    FinalKind     = ''
                    Ops           = [System.Collections.ArrayList]::new()
                    Results       = [System.Collections.ArrayList]::new()
                }
                $null = $planOrder.Add($rel)
            }

            $plan = $plans[$rel]
            if ($plan.Ops.Count -gt 0 -and
                (([string]$plan.Ops[0].Op -ne 'replace') -or ([string]$op.Op -ne 'replace'))) {
                throw "BATCH_PATH_OPERATION_CONFLICT: repeated path '$rel' may contain replace operations only"
            }
            $null = $plan.Ops.Add($op)

            $exists = [bool]$plan.InitialExists
            switch ($op.Op) {
                'create' {
                    if ($exists) { throw "FILE_ALREADY_EXISTS: $rel" }
                    # Empty string content is allowed for create (e.g. __init__.py, .gitkeep).
                    if ($null -eq $op.Content) { throw "TOOL_ARGUMENTS_INVALID: create requires content field" }
                    $newBytes = ConvertTo-EditUtf8Bytes -Content ([string]$op.Content)
                    $newSha = Get-EditBytesSha256 -Bytes $newBytes
                    $plan.WorkingBytes = $newBytes
                    $plan.FinalContent = [string]$op.Content
                    $plan.FinalKind = 'create'
                    $logicalResult = [PSCustomObject]@{ path = $rel; op = 'create'; ok = $true; before_sha = $null; after_sha = $newSha; sha = $newSha }
                }
                'delete' {
                    if (-not $exists) { throw "FILE_NOT_FOUND: $rel" }
                    if (-not $op.ExpectedSha) {
                        throw "TOOL_ARGUMENTS_INVALID: delete requires expected_sha (fresh-read required)"
                    }
                    if ($plan.InitialSha -ne $op.ExpectedSha) {
                        throw "FILE_NOT_FRESH: $rel expected $($op.ExpectedSha) live $($plan.InitialSha)"
                    }
                    $plan.WorkingBytes = $null
                    $plan.FinalContent = $null
                    $plan.FinalKind = 'delete'
                    $logicalResult = [PSCustomObject]@{ path = $rel; op = 'delete'; ok = $true; before_sha = $plan.InitialSha; after_sha = $null; sha = $null }
                }
                'rewrite' {
                    if (-not $exists) { throw "FILE_NOT_FOUND: $rel" }
                    if (-not $op.ExpectedSha) {
                        throw "TOOL_ARGUMENTS_INVALID: rewrite requires expected_sha (fresh-read required)"
                    }
                    if ($plan.InitialSha -ne $op.ExpectedSha) {
                        throw "FILE_NOT_FRESH: $rel expected $($op.ExpectedSha) live $($plan.InitialSha)"
                    }
                    if ($null -eq $op.Content) { throw "TOOL_ARGUMENTS_INVALID: rewrite requires content" }
                    $newBytes = ConvertTo-EditUtf8Bytes -Content ([string]$op.Content)
                    $newSha = Get-EditBytesSha256 -Bytes $newBytes
                    $plan.WorkingBytes = $newBytes
                    $plan.FinalContent = [string]$op.Content
                    $plan.FinalKind = 'rewrite'
                    $logicalResult = [PSCustomObject]@{ path = $rel; op = 'rewrite'; ok = $true; before_sha = $plan.InitialSha; after_sha = $newSha; sha = $newSha }
                }
                'replace' {
                    if (-not $exists) { throw "FILE_NOT_FOUND: $rel" }
                    if (-not $op.ExpectedSha) {
                        throw "TOOL_ARGUMENTS_INVALID: replace requires expected_sha (fresh-read required)"
                    }
                    # Every replace in one batch proves freshness against the
                    # same sealed on-disk preimage. Its result SHA still chains
                    # from the preceding in-memory replacement.
                    if ($plan.InitialSha -ne $op.ExpectedSha) {
                        throw "FILE_NOT_FRESH: $rel expected $($op.ExpectedSha) live $($plan.InitialSha)"
                    }
                    if (-not $op.Context) {
                        throw "TOOL_ARGUMENTS_INVALID: replace requires context (exact match snippet)"
                    }
                    $content = [System.Text.Encoding]::UTF8.GetString([byte[]]$plan.WorkingBytes)
                    $idx = $content.IndexOf($op.Context, [StringComparison]::Ordinal)
                    if ($idx -lt 0) {
                        throw "CONTEXT_NOT_FOUND: path=$rel context_len=$($op.Context.Length)"
                    }
                    $second = $content.IndexOf($op.Context, $idx + 1, [StringComparison]::Ordinal)
                    if ($second -ge 0) {
                        throw "CONTEXT_NOT_UNIQUE: path=$rel"
                    }
                    if ($op.OldText -and -not $op.Context.Contains($op.OldText)) {
                        throw "CONTEXT_NOT_FOUND: old_text not inside context"
                    }
                    $beforeSha = Get-EditBytesSha256 -Bytes ([byte[]]$plan.WorkingBytes)
                    $before = $content.Substring(0, $idx)
                    $after = $content.Substring($idx + $op.Context.Length)
                    if ($op.OldText) {
                        $ctxIdx = $op.Context.IndexOf($op.OldText, [StringComparison]::Ordinal)
                        $ctxNew = $op.Context.Substring(0, $ctxIdx) + $op.NewText + $op.Context.Substring($ctxIdx + $op.OldText.Length)
                        $newContent = $before + $ctxNew + $after
                    } else {
                        $newContent = $before + $op.NewText + $after
                    }
                    $newBytes = ConvertTo-EditUtf8Bytes -Content $newContent
                    $newSha = Get-EditBytesSha256 -Bytes $newBytes
                    $plan.WorkingBytes = $newBytes
                    $plan.FinalContent = $newContent
                    $plan.FinalKind = 'replace'
                    $warning = if ($newSha -eq $beforeSha) { 'NO_EFFECTIVE_CHANGE' } else { $null }
                    $logicalResult = [PSCustomObject]@{ path = $rel; op = 'replace'; ok = $true; before_sha = $beforeSha; after_sha = $newSha; sha = $newSha; warning = $warning }
                }
            }
            $null = $plan.Results.Add($logicalResult)
        }
    } catch {
        $err = $_.Exception.Message
        $code = if ($err -match '^(FILE_|CONTEXT_|PATH_|TOOL_|SENSITIVE|BATCH_|REPARSE_POINT_FORBIDDEN|HARDLINK_COUNT_UNAVAILABLE)') { ($err -split ':')[0] } else { 'EDIT_VALIDATION_FAILED' }
        return @{
            ok        = $false
            error     = $code
            message   = $err
            results   = @()
            divergent = @()
        }
    }

    # §9 TOCTOU: re-verify every initial state immediately before the first side-effect.
    try {
        foreach ($key in @($planOrder)) {
            $plan = $plans[$key]
            $full = (Resolve-WorkspacePath -Workspace $ws -RelativePath $key -Mode Write).Full
            if ($plan.InitialExists) {
                if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
                    throw "FILE_NOT_FRESH: $key disappeared before write"
                }
                $liveBytes = [System.IO.File]::ReadAllBytes($full)
                $pre = [byte[]]$plan.InitialBytes
                if ($liveBytes.Length -ne $pre.Length) {
                    throw "FILE_NOT_FRESH: $key changed before write (size)"
                }
                for ($i = 0; $i -lt $pre.Length; $i++) {
                    if ($liveBytes[$i] -ne $pre[$i]) {
                        throw "FILE_NOT_FRESH: $key changed before write (content)"
                    }
                }
            } elseif (Test-Path -LiteralPath $full) {
                throw "FILE_NOT_FRESH: $key appeared before create"
            }
        }
    } catch {
        $err = $_.Exception.Message
        $code = if ($err -match '^(FILE_NOT_FRESH|REPARSE_POINT_FORBIDDEN|HARDLINK_COUNT_UNAVAILABLE)') { ($err -split ':')[0] } else { 'EDIT_VALIDATION_FAILED' }
        return @{
            ok        = $false
            error     = $code
            message   = $err
            results   = @()
            divergent = @()
        }
    }

    # Phase 2: apply
    try {
        foreach ($rel in @($planOrder)) {
            $plan = $plans[$rel]
            $resolved = Resolve-WorkspacePath -Workspace $ws -RelativePath $rel -Mode Write
            $full = $resolved.Full
            # Track the path before its one and only side-effect so even a
            # partial write failure restores the sealed preimage.
            $null = $appliedPaths.Add($rel)

            switch ($plan.FinalKind) {
                'create' {
                    Write-FileExactUtf8NoBom -FullPath $full -Content ([string]$plan.FinalContent)
                    $newSha = Get-FileSha256Exact -FullPath $full
                    $expectedFinalSha = Get-EditBytesSha256 -Bytes ([byte[]]$plan.WorkingBytes)
                    if ($newSha -ne $expectedFinalSha) { throw "EDIT_FINAL_SHA_MISMATCH: $rel" }
                    $null = Get-OrRecordFileState -Workspace $ws -RelativePath $rel -AsInitial $true -ForceRefresh $true
                }
                'delete' {
                    Remove-Item -LiteralPath $full -Force
                    if (Test-Path -LiteralPath $full) { throw "EDIT_DELETE_FAILED: $rel" }
                    if ($ws.KnownStates.ContainsKey($rel)) { $null = $ws.KnownStates.Remove($rel) }
                    $null = Get-OrRecordFileState -Workspace $ws -RelativePath $rel -ForceRefresh $true
                }
                'rewrite' {
                    Write-FileExactUtf8NoBom -FullPath $full -Content ([string]$plan.FinalContent)
                    $newSha = Get-FileSha256Exact -FullPath $full
                    $expectedFinalSha = Get-EditBytesSha256 -Bytes ([byte[]]$plan.WorkingBytes)
                    if ($newSha -ne $expectedFinalSha) { throw "EDIT_FINAL_SHA_MISMATCH: $rel" }
                    $null = Get-OrRecordFileState -Workspace $ws -RelativePath $rel -ForceRefresh $true
                }
                'replace' {
                    Write-FileExactUtf8NoBom -FullPath $full -Content ([string]$plan.FinalContent)
                    $newSha = Get-FileSha256Exact -FullPath $full
                    $expectedFinalSha = Get-EditBytesSha256 -Bytes ([byte[]]$plan.WorkingBytes)
                    if ($newSha -ne $expectedFinalSha) { throw "EDIT_FINAL_SHA_MISMATCH: $rel" }
                    $null = Get-OrRecordFileState -Workspace $ws -RelativePath $rel -ForceRefresh $true
                }
                default { throw "EDIT_PLAN_INVALID: no final operation for $rel" }
            }
            foreach ($logicalResult in @($plan.Results)) {
                $null = $results.Add($logicalResult)
            }
        }
        $Batch.Applied = $true
        return @{
            ok        = $true
            results   = $results
            divergent = @()
        }
    } catch {
        # Phase 3: rollback from memory preimages
        $rollbackErrors = [System.Collections.ArrayList]::new()
        foreach ($rel in $appliedPaths) {
            try {
                $full = (Resolve-WorkspacePath -Workspace $ws -RelativePath $rel -Mode Write).Full
                if ($Batch.Preimages.ContainsKey($rel)) {
                    $bytes = $Batch.Preimages[$rel]
                    $dir = Split-Path -Parent $full
                    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
                        New-Item -ItemType Directory -Path $dir -Force | Out-Null
                    }
                    [System.IO.File]::WriteAllBytes($full, $bytes)
                    $null = Get-OrRecordFileState -Workspace $ws -RelativePath $rel -ForceRefresh $true
                } else {
                    if (Test-Path -LiteralPath $full) { Remove-Item -LiteralPath $full -Force }
                    if ($ws.KnownStates.ContainsKey($rel)) { $null = $ws.KnownStates.Remove($rel) }
                }
            } catch {
                $null = $rollbackErrors.Add("$rel : $($_.Exception.Message)")
                $null = $Batch.Divergent.Add($rel)
            }
        }
        if ($rollbackErrors.Count -gt 0) {
            return @{
                ok        = $false
                error     = 'BATCH_ROLLBACK_FAILED'
                message   = ($rollbackErrors -join '; ')
                results   = $results
                divergent = @($Batch.Divergent)
            }
        }
        return @{
            ok        = $false
            error     = 'EDIT_APPLY_FAILED'
            message   = $_.Exception.Message
            results   = $results
            divergent = @()
        }
    }
}

Export-ModuleMember -Function @(
    'New-EditBatch',
    'Add-EditOp',
    'Invoke-EditBatch'
)
