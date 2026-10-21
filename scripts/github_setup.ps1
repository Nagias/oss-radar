<#
.SYNOPSIS
  Tạo repo GitHub cho dự án, đẩy nhánh main lần đầu và bật bảo vệ nhánh main (trả nợ D-002).

.DESCRIPTION
  Chạy MỘT lần, do chủ dự án tự chạy: cần GitHub CLI đã đăng nhập (`gh auth login`).
  Agent không chạy script này thay chủ dự án vì nó tạo repo trên tài khoản của họ và đẩy thẳng main.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File ".\scripts\github_setup.ps1" -Visibility public
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("public", "private")]
    [string]$Visibility,

    [string]$Name = "oss-radar"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Invoke-Step {
    param([string]$Step, [scriptblock]$Command)
    Write-Host "==> $Step"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Thất bại ở bước: $Step (mã lỗi $LASTEXITCODE)"
    }
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "Chưa cài GitHub CLI. Cài bằng: winget install --id GitHub.cli  rồi chạy: gh auth login"
}
Invoke-Step "Kiểm tra đăng nhập GitHub" { gh auth status }

$branch = git branch --show-current
if ($branch -ne "main") {
    throw "Hãy chuyển về nhánh main trước khi chạy (đang ở: $branch)."
}
if (git status --porcelain) {
    throw "Còn thay đổi chưa commit. Hãy commit hoặc cất đi trước khi chạy."
}

Invoke-Step "Tạo repo $Name ($Visibility)" {
    gh repo create $Name "--$Visibility" --source . --remote origin `
        --description "OSS Radar - quét, lọc và đề xuất repo GitHub chất lượng (chạy local)"
}
Invoke-Step "Đẩy nhánh main lần đầu" { git push -u origin main }

$owner = gh api user --jq .login
$repo = "$owner/$Name"

Invoke-Step "Chỉ cho squash-merge, tự xoá nhánh sau khi merge" {
    gh api -X PATCH "repos/$repo" -F allow_squash_merge=true -F allow_merge_commit=false `
        -F allow_rebase_merge=false -F delete_branch_on_merge=true --silent
}

Write-Host "==> Bật bảo vệ nhánh main"
gh api -X PUT "repos/$repo/branches/main/protection" --input "scripts/github/branch-protection.json" --silent
if ($LASTEXITCODE -ne 0) {
    if ($Visibility -eq "private") {
        Write-Warning ("GitHub từ chối: repo private trên gói Free không có bảo vệ nhánh. " +
            "Cần GitHub Pro, hoặc chuyển repo sang public rồi chạy lại: " +
            "gh api -X PUT repos/$repo/branches/main/protection --input scripts/github/branch-protection.json")
    }
    throw "Bật bảo vệ nhánh thất bại."
}

Write-Host "Xong: https://github.com/$repo - main chỉ nhận Pull Request có job 'check' xanh."
