"""The setup packs for a Windows server with no internet: what goes into them besides the application itself.

Two packs are made from the same application layer (app/app.jar, web/, release/):
  install  first setup on an empty machine. Carries its own runtime (Java, PostgreSQL, the service wrapper, the
           Visual C++ runtime PostgreSQL needs), creates the database, registers two Windows services and starts them.
  update   for a machine that was set up with an install pack. No runtime. Backs the database up, swaps the
           application, and puts the earlier application and the backup back if the new one does not come up.

The scripts are PowerShell (Windows PowerShell 5.1, which every supported Windows has) started through .bat files.
They are written with a UTF-8 byte order mark, because Windows PowerShell reads a script without one in the
machine's own code page and Korean text would break.
"""
import shutil
import subprocess
import zipfile
from pathlib import Path

VENDOR_FILES = {'jre': 'jre17.zip', 'winsw': 'winsw.exe', 'vc': 'vc_redist.x64.exe'}
SOURCES = {'jre17.zip': 'https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jre/hotspot/normal/eclipse',
           'winsw.exe': 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe',
           'vc_redist.x64.exe': 'https://aka.ms/vs/17/release/vc_redist.x64.exe',
           'pgsql': 'https://get.enterprisedb.com/postgresql/postgresql-{version}-windows-x64-binaries.zip'}
POSTGRES_VERSIONS = ('17.11-1', '17.10-1', '17.9-1', '17.8-1', '17.7-1')

COMMON = r'''# 설치·업데이트·백업 스크립트가 함께 쓰는 것들.
$ErrorActionPreference = 'Stop'
$PackRoot = Split-Path -Parent $PSScriptRoot

function Assert-Admin {
    $me = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw '관리자 권한으로 실행해야 합니다. install.bat (또는 update.bat) 을 마우스 오른쪽 단추로 눌러 "관리자 권한으로 실행" 하세요.'
    }
}

# 바깥 프로그램을 실행하고 출력(오류 출력 포함)을 글자로 돌려준다. 성공 여부는 $LASTEXITCODE 로 본다.
# (Windows PowerShell 은 오류 출력을 받으면 그것만으로 멈추므로, 이 안에서만 멈추지 않게 한다.)
function Invoke-Native([string]$exe, [string[]]$arguments) {
    $ErrorActionPreference = 'Continue'
    (& $exe @arguments 2>&1 | ForEach-Object { "$_" }) -join "`n"
}

function Copy-Folder([string]$from, [string]$to) {
    if (Test-Path $to) { Remove-Item $to -Recurse -Force }
    Copy-Item $from $to -Recurse
}

function Say([string]$text) { Write-Host ('[' + (Get-Date -Format 'HH:mm:ss') + '] ' + $text) }

function New-Secret([int]$length) {
    $letters = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'.ToCharArray()
    $bytes = New-Object byte[] $length
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    -join ($bytes | ForEach-Object { $letters[$_ % $letters.Length] })
}

# 관리자와 시스템만 읽을 수 있게 (비밀번호가 든 파일).
function Protect-File([string]$path) {
    & icacls $path /inheritance:r /grant:r '*S-1-5-32-544:(F)' '*S-1-5-18:(F)' | Out-Null
}

function Read-Config([string]$dir) {
    $file = Join-Path $dir 'config.json'
    if (-not (Test-Path $file)) { throw "$dir 에 설치된 것이 없습니다 (config.json 없음)." }
    Get-Content $file -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Read-Version([string]$folder) {
    $file = Join-Path $folder 'VERSION.json'
    if (Test-Path $file) { Get-Content $file -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
}

# PostgreSQL 도구를 설치된 DB 에 대고 실행한다. 비밀번호는 환경 변수로만 건넨다.
function Invoke-Pg([string]$dir, $config, [string]$tool, [string[]]$arguments) {
    $env:PGPASSWORD = $config.dbPassword
    try {
        $exe = Join-Path $dir "runtime\pgsql\bin\$tool.exe"
        $output = Invoke-Native $exe (@('-h', '127.0.0.1', '-p', "$($config.dbPort)", '-U', 'mdi') + $arguments)
        if ($LASTEXITCODE -ne 0) { throw "$tool 실패: $output" }
        $output
    } finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
}

function Wait-Db([string]$dir, $config, [int]$seconds = 90) {
    $ready = Join-Path $dir 'runtime\pgsql\bin\pg_isready.exe'
    for ($i = 0; $i -lt $seconds; $i++) {
        Invoke-Native $ready @('-h', '127.0.0.1', '-p', "$($config.dbPort)", '-q') | Out-Null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 1
    }
    throw "데이터베이스가 $seconds 초 안에 시작하지 않았습니다. $dir\data\pg\log 를 확인하세요."
}

function Backup-Db([string]$dir, $config) {
    $folder = Join-Path $dir 'backups'
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $file = Join-Path $folder ('db-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.dump')
    Invoke-Pg $dir $config 'pg_dump' @('-Fc', '-f', $file, 'app') | Out-Null
    if (-not (Test-Path $file) -or (Get-Item $file).Length -eq 0) { throw '백업 파일이 만들어지지 않았습니다.' }
    $file
}

function Restore-Db([string]$dir, $config, [string]$file) {
    Invoke-Pg $dir $config 'psql' @('-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-c', 'DROP DATABASE IF EXISTS app WITH (FORCE)', '-c', 'CREATE DATABASE app OWNER mdi') | Out-Null
    Invoke-Pg $dir $config 'pg_restore' @('-d', 'app', '--no-owner', $file) | Out-Null
}

# 서버(자바 프로그램)를 윈도우 서비스로 등록하는 설정 파일. 서비스 이름과 같은 이름의 exe 옆에 둔다.
function Write-AppService([string]$dir, $config) {
    $name = $config.name + '-APP'
    $web = ($dir -replace '\\', '/') + '/web/'
    $xml = @"
<service>
  <id>$name</id>
  <name>$name</name>
  <description>업무 시스템 서버 ($dir)</description>
  <executable>$dir\runtime\jre\bin\java.exe</executable>
  <arguments>-Xmx1g -Duser.timezone=UTC -Dfile.encoding=UTF-8 -jar "$dir\app\app.jar"</arguments>
  <workingdirectory>$dir</workingdirectory>
  <env name="SERVER_PORT" value="$($config.port)"/>
  <env name="DB_URL" value="jdbc:postgresql://127.0.0.1:$($config.dbPort)/app"/>
  <env name="SPRING_DATASOURCE_USERNAME" value="mdi"/>
  <env name="SPRING_DATASOURCE_PASSWORD" value="$($config.dbPassword)"/>
  <env name="WORKSPACE_ADMIN_USERNAME" value="admin"/>
  <env name="WORKSPACE_ADMIN_PASSWORD" value="$($config.adminFirstPassword)"/>
  <env name="SPRING_WEB_RESOURCES_STATIC_LOCATIONS" value="file:$web"/>
  <env name="APP_RELEASE_DIR" value="$dir\release"/>
  <env name="APP_TIMEZONE" value="$($config.timezone)"/>
  <depend>$($config.name)-DB</depend>
  <logpath>$dir\logs</logpath>
  <log mode="roll-by-size"><sizeThreshold>10240</sizeThreshold><keepFiles>8</keepFiles></log>
  <onfailure action="restart" delay="15 sec"/>
</service>
"@
    $exe = Join-Path $dir "service\$name.exe"
    New-Item -ItemType Directory -Force -Path (Join-Path $dir 'service'), (Join-Path $dir 'logs') | Out-Null
    if (-not (Test-Path $exe)) { Copy-Item (Join-Path $dir 'runtime\winsw.exe') $exe }
    $file = Join-Path $dir "service\$name.xml"
    [IO.File]::WriteAllText($file, $xml, (New-Object Text.UTF8Encoding($false)))
    Protect-File $file
    $exe
}

# 서버가 뜨고, 팩의 화면 정의를 다 받아들였는지 본다. 'ok' 또는 사유를 돌려준다.
function Wait-App([string]$dir, $config, [int]$seconds = 240) {
    $url = "http://127.0.0.1:$($config.port)/"
    $up = $false
    for ($i = 0; $i -lt $seconds; $i += 3) {
        try { $answer = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5; if ($answer.StatusCode -eq 200) { $up = $true; break } } catch { }
        Start-Sleep -Seconds 3
    }
    if (-not $up) { return "서버가 $seconds 초 안에 응답하지 않았습니다. $dir\logs 를 확인하세요." }
    Start-Sleep -Seconds 3
    $status = (Invoke-Pg $dir $config 'psql' @('-d', 'app', '-At', '-c', "select setting_value from sys_settings where setting_key='release_status'") | Out-String).Trim()
    $detail = (Invoke-Pg $dir $config 'psql' @('-d', 'app', '-At', '-c', "select setting_value from sys_settings where setting_key='release_detail'") | Out-String).Trim()
    if ($status -eq 'ok') { Say "화면 반영: $detail"; return 'ok' }
    "화면을 반영하지 못했습니다: $detail"
}

function Copy-Layer([string]$from, [string]$to) {
    foreach ($part in 'app', 'web', 'release') { Copy-Folder (Join-Path $from $part) (Join-Path $to $part) }
    Copy-Item (Join-Path $from 'VERSION.json') (Join-Path $to 'VERSION.json') -Force
}
'''

INSTALL = r'''# 최초 셋업: 빈 윈도우에 런타임(자바, PostgreSQL)과 데이터베이스, 서버를 올리고 서비스로 등록한다.
#   install.bat                      C:\ERP 에, 8080 포트로
#   install.bat -Dir D:\ERP -Port 80 -Name ERP2      위치·포트·서비스 이름을 바꿔서 (한 서버에 두 벌을 둘 때 이름과 포트를 다르게)
param([string]$Dir = 'C:\ERP', [int]$Port = 8080, [int]$DbPort = 5433, [string]$Name = 'ERP', [switch]$NoFirewall)
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Admin
if (-not (Test-Path (Join-Path $PackRoot 'runtime\pgsql\bin\initdb.exe'))) { throw '이 팩에는 런타임이 없습니다 (업데이트 팩입니다). 최초 셋업 팩으로 설치하세요.' }
if (Test-Path (Join-Path $Dir 'config.json')) { throw "$Dir 에는 이미 설치되어 있습니다. 새 버전으로 올리려면 업데이트 팩의 update.bat 을 쓰세요." }
if (Get-Service -Name "$Name-DB", "$Name-APP" -ErrorAction SilentlyContinue) { throw "$Name-DB 또는 $Name-APP 서비스가 이미 있습니다. -Name 으로 다른 이름을 주세요." }
foreach ($used in $Port, $DbPort) {
    if (Get-NetTCPConnection -LocalPort $used -State Listen -ErrorAction SilentlyContinue) { throw "$used 포트를 다른 프로그램이 쓰고 있습니다. -Port (또는 -DbPort) 로 다른 포트를 주세요." }
}

Say "설치 위치 $Dir, 접속 포트 $Port"
New-Item -ItemType Directory -Force -Path $Dir, (Join-Path $Dir 'data'), (Join-Path $Dir 'backups'), (Join-Path $Dir 'logs') | Out-Null

Say '런타임 복사 (자바, PostgreSQL)'
Copy-Folder (Join-Path $PackRoot 'runtime') (Join-Path $Dir 'runtime')
Copy-Folder (Join-Path $PackRoot 'scripts') (Join-Path $Dir 'scripts')
foreach ($file in 'update.bat', 'backup.bat', 'restore.bat', 'uninstall.bat', 'README.md') { Copy-Item (Join-Path $PackRoot $file) (Join-Path $Dir $file) -Force }
Copy-Layer $PackRoot $Dir

if (-not (Test-Path (Join-Path $env:SystemRoot 'System32\vcruntime140.dll'))) {
    Say 'Visual C++ 런타임 설치 (PostgreSQL 에 필요)'
    $run = Start-Process -FilePath (Join-Path $Dir 'runtime\vc_redist.x64.exe') -ArgumentList '/install', '/quiet', '/norestart' -Wait -PassThru
    if ($run.ExitCode -notin 0, 1638, 3010) { throw "Visual C++ 런타임 설치 실패 (코드 $($run.ExitCode))." }
}

$config = [pscustomobject]@{ name = $Name; port = $Port; dbPort = $DbPort; dbPassword = (New-Secret 24); adminFirstPassword = (New-Secret 12); timezone = 'Asia/Seoul' }
$configFile = Join-Path $Dir 'config.json'
[IO.File]::WriteAllText($configFile, ($config | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
Protect-File $configFile

Say '데이터베이스 만들기'
$data = Join-Path $Dir 'data\pg'
$passwordFile = Join-Path $Dir 'data\pw.tmp'
[IO.File]::WriteAllText($passwordFile, $config.dbPassword, (New-Object Text.UTF8Encoding($false)))
try {
    $made = Invoke-Native (Join-Path $Dir 'runtime\pgsql\bin\initdb.exe') @('-D', $data, '-U', 'mdi', '-A', 'scram-sha-256', "--pwfile=$passwordFile", '-E', 'UTF8', '--locale=C')
    if ($LASTEXITCODE -ne 0) { throw "데이터베이스 초기화 실패: $made" }
} finally { Remove-Item $passwordFile -Force -ErrorAction SilentlyContinue }
# 이 서버 안에서만 접속을 받고, 시각은 UTC 로 적는다 (화면이 보는 사람의 시간대로 바꿔 보여 준다).
Add-Content -Path (Join-Path $data 'postgresql.conf') -Encoding ASCII -Value "`nlisten_addresses = '127.0.0.1'`nport = $DbPort`ntimezone = 'UTC'`nlog_timezone = 'UTC'`nlogging_collector = on`nlog_directory = 'log'`n"
$registered = Invoke-Native (Join-Path $Dir 'runtime\pgsql\bin\pg_ctl.exe') @('register', '-N', "$Name-DB", '-D', $data, '-S', 'auto', '-w')
if ($LASTEXITCODE -ne 0) { throw "DB 서비스 등록 실패: $registered" }
Start-Service "$Name-DB"
Wait-Db $Dir $config
Invoke-Pg $Dir $config 'psql' @('-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-c', 'CREATE DATABASE app OWNER mdi') | Out-Null

Say '서버 서비스 등록과 시작'
$service = Write-AppService $Dir $config
$installed = Invoke-Native $service @('install')
if ($LASTEXITCODE -ne 0) { throw "서버 서비스 등록 실패: $installed" }
Start-Service "$Name-APP"

if (-not $NoFirewall) {
    New-NetFirewallRule -DisplayName "$Name-APP ($Port)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -ErrorAction SilentlyContinue | Out-Null
}

Say '서버가 뜨기를 기다리는 중 (처음에는 1~2분 걸립니다)'
$result = Wait-App $Dir $config
$note = Join-Path $Dir 'admin-first-password.txt'
[IO.File]::WriteAllText($note, "아이디: admin`r`n첫 비밀번호: $($config.adminFirstPassword)`r`n들어가서 비밀번호를 바꾼 뒤 이 파일은 지우세요.`r`n", (New-Object Text.UTF8Encoding($true)))
Protect-File $note
if ($result -ne 'ok') { throw "설치는 됐지만 확인에 실패했습니다: $result" }
$version = Read-Version $Dir
Say "설치했습니다 (버전 $($version.stamp), 화면 $($version.screens)개)."
Write-Host ''
Write-Host "  접속 주소: http://<이 서버의 주소>:$Port   (이 서버에서는 http://localhost:$Port)"
Write-Host "  관리자 첫 비밀번호: $note 파일에 있습니다. 들어가서 바꾸세요."
Write-Host "  서비스: $Name-DB (데이터베이스), $Name-APP (서버) - 윈도우가 켜지면 자동으로 시작합니다."
Write-Host "  백업: $Dir\backup.bat   ·   새 버전으로 올리기: 업데이트 팩의 update.bat"
'''

UPDATE = r'''# 업데이트: 이미 설치된 곳의 서버 프로그램·화면·화면 정의를 이 팩의 것으로 바꾼다. 자료, 첨부 파일, 사용자, 권한은 그대로 둔다.
# 먼저 데이터베이스를 백업하고, 새 서버가 뜨지 않거나 화면 정의가 받아들여지지 않으면 이전 프로그램과 백업으로 되돌린다.
#   update.bat                    C:\ERP 에 설치된 것을
#   update.bat -Dir D:\ERP       다른 위치에 설치된 것을
#   update.bat -Force             설치된 것보다 오래된 팩으로도 (되돌릴 때)
param([string]$Dir = 'C:\ERP', [switch]$Force)
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Admin
$config = Read-Config $Dir
$installed = Read-Version $Dir
$coming = Read-Version $PackRoot
if (-not $coming) { throw '이 폴더는 셋업 팩이 아닙니다 (VERSION.json 없음).' }
if ((Resolve-Path $PackRoot).Path -eq (Resolve-Path $Dir).Path) { throw '설치된 폴더가 아니라, 새로 받은 팩을 푼 폴더의 update.bat 을 실행하세요.' }
if ($installed -and $installed.stamp -eq $coming.stamp) { Say "이미 이 버전($($coming.stamp))입니다. 할 일이 없습니다."; return }
if ($installed -and ($installed.stamp -gt $coming.stamp) -and -not $Force) {
    throw "설치된 버전($($installed.stamp))이 이 팩($($coming.stamp))보다 새것입니다. 일부러 되돌리는 것이라면 -Force 를 붙이세요."
}
$app = "$($config.name)-APP"
Say "업데이트: $($installed.stamp) -> $($coming.stamp)  ($Dir)"

Wait-Db $Dir $config 30
Say '데이터베이스 백업'
$backup = Backup-Db $Dir $config
Say "  $backup"

Say '서버 멈춤'
Stop-Service $app -Force
$previous = Join-Path $Dir 'previous'
if (Test-Path $previous) { Remove-Item $previous -Recurse -Force }
New-Item -ItemType Directory -Force -Path $previous | Out-Null
foreach ($part in 'app', 'web', 'release') { Copy-Item (Join-Path $Dir $part) (Join-Path $previous $part) -Recurse }
if (Test-Path (Join-Path $Dir 'VERSION.json')) { Copy-Item (Join-Path $Dir 'VERSION.json') (Join-Path $previous 'VERSION.json') }

Say '새 프로그램과 화면으로 교체'
Copy-Layer $PackRoot $Dir
Copy-Folder (Join-Path $PackRoot 'scripts') (Join-Path $Dir 'scripts')
foreach ($file in 'update.bat', 'backup.bat', 'restore.bat', 'uninstall.bat', 'README.md') { Copy-Item (Join-Path $PackRoot $file) (Join-Path $Dir $file) -Force }
Write-AppService $Dir $config | Out-Null
Start-Service $app
Say '서버가 뜨기를 기다리는 중'
$result = Wait-App $Dir $config
if ($result -eq 'ok') {
    Say "업데이트했습니다 (버전 $($coming.stamp), 화면 $($coming.screens)개). 이전 프로그램은 $previous 에, 백업은 $backup 에 있습니다."
    return
}

Say "새 버전이 올라오지 않았습니다: $result"
Say '이전 프로그램과 백업으로 되돌립니다'
Stop-Service $app -Force -ErrorAction SilentlyContinue
Copy-Layer $previous $Dir
Restore-Db $Dir $config $backup
Start-Service $app
$again = Wait-App $Dir $config
if ($again -eq 'ok') { throw "업데이트하지 못했습니다 ($result). 이전 버전($($installed.stamp))으로 되돌려 다시 운영 중입니다." }
throw "업데이트하지 못했고($result), 되돌린 뒤에도 서버가 올라오지 않았습니다($again). $Dir\logs 와 백업 $backup 을 확인하세요."
'''

BACKUP = r'''# 데이터베이스 전체를 backups 폴더에 파일 하나로 받는다 (자료, 첨부 파일, 사용자, 권한 모두).
param([string]$Dir = (Split-Path -Parent $PSScriptRoot))
. (Join-Path $PSScriptRoot 'common.ps1')
$config = Read-Config $Dir
$file = Backup-Db $Dir $config
Say "백업: $file"
'''

RESTORE = r'''# 백업 파일로 되돌린다: restore.bat C:\ERP\backups\db-20260101-120000.dump   (지금 자료는 그 시점의 것으로 바뀐다)
param([Parameter(Mandatory = $true)][string]$File, [string]$Dir = (Split-Path -Parent $PSScriptRoot))
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Admin
if (-not (Test-Path $File)) { throw "백업 파일이 없습니다: $File" }
$config = Read-Config $Dir
$app = "$($config.name)-APP"
Say '되돌리기 전에 지금 상태를 먼저 백업합니다'
Say ("  " + (Backup-Db $Dir $config))
Stop-Service $app -Force
Restore-Db $Dir $config (Resolve-Path $File).Path
Start-Service $app
$result = Wait-App $Dir $config
if ($result -ne 'ok') { throw "되돌렸지만 서버 확인에 실패했습니다: $result" }
Say '되돌렸습니다.'
'''

UNINSTALL = r'''# 서비스 두 개를 내린다. 자료(data, backups)와 폴더는 지우지 않는다 - 필요 없으면 폴더를 직접 지운다.
param([string]$Dir = (Split-Path -Parent $PSScriptRoot))
. (Join-Path $PSScriptRoot 'common.ps1')
Assert-Admin
$config = Read-Config $Dir
$name = $config.name
Stop-Service "$name-APP" -Force -ErrorAction SilentlyContinue
Invoke-Native (Join-Path $Dir "service\$name-APP.exe") @('uninstall') | Out-Null
Stop-Service "$name-DB" -Force -ErrorAction SilentlyContinue
Invoke-Native (Join-Path $Dir 'runtime\pgsql\bin\pg_ctl.exe') @('unregister', '-N', "$name-DB") | Out-Null
Remove-NetFirewallRule -DisplayName "$name-APP ($($config.port))" -ErrorAction SilentlyContinue
Say "서비스를 내렸습니다. 자료는 $Dir 에 그대로 있습니다."
'''

SCRIPTS = {'common.ps1': COMMON, 'install.ps1': INSTALL, 'update.ps1': UPDATE, 'backup.ps1': BACKUP, 'restore.ps1': RESTORE, 'uninstall.ps1': UNINSTALL}


def _bat(script):
    """A launcher that keeps the window open, so the outcome can be read. Plain ASCII: a .bat is read in the console's own code page."""
    return ('@echo off\r\nchcp 65001 >nul\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\\' + script + '" %*\r\n'
            'echo.\r\nif errorlevel 1 (echo [FAILED] See the message above.) else (echo [DONE])\r\npause\r\n')


def readme(version, kind):
    service = version.get('service', 'ERP')
    return _readme(version, kind == 'install').replace(':\\ERP', f':\\{service}').replace('`ERP-DB`', f'`{service}-DB`').replace('`ERP-APP`', f'`{service}-APP`')


def _readme(version, first):
    return f"""# {version.get('project', '')} 운영 셋업 팩 - {'최초 셋업' if first else '업데이트'}

버전 {version['stamp']} · 만든 때 {version['made_at']} · 화면 {version['screens']}개

대상: 윈도우 서버 또는 PC (64비트, Windows 10 / Server 2016 이상). 인터넷이 없어도 됩니다.

""" + ("""## 최초 셋업 (빈 서버에 처음 설치)

이 팩 하나에 필요한 것이 모두 들어 있습니다: 자바 실행 환경, PostgreSQL 데이터베이스, 서버 프로그램, 화면.

1. 이 zip 을 서버에 풉니다. (한글이 없는 짧은 경로를 권합니다. 예: `C:\\pack`)
2. `install.bat` 을 마우스 오른쪽 단추로 눌러 **관리자 권한으로 실행**합니다.
3. 끝나면 안내된 주소로 들어갑니다. 관리자 아이디는 `admin`, 첫 비밀번호는 `C:\\ERP\\admin-first-password.txt` 에 있습니다. 들어가서 바꾸세요.

설치가 하는 일: `C:\\ERP` 에 런타임과 프로그램을 복사 → 데이터베이스 생성 → 윈도우 서비스 두 개(`ERP-DB`, `ERP-APP`) 등록과 시작 →
방화벽에 접속 포트 열기 → 화면 정의·공통 코드·메뉴 반영 → 확인.

위치나 포트를 바꾸려면 관리자 명령 창에서: `install.bat -Dir D:\\ERP -Port 80`
이미 설치된 서버에서는 실행이 거절됩니다. 그때는 업데이트 팩을 씁니다.
""" if first else """## 업데이트 (이미 설치된 서버를 새 버전으로)

최초 셋업 팩으로 설치한 서버에만 씁니다. 런타임은 들어 있지 않습니다.

1. 이 zip 을 서버의 아무 곳에나 풉니다. (설치 폴더 `C:\\ERP` 안이 아닌 곳)
2. `update.bat` 을 마우스 오른쪽 단추로 눌러 **관리자 권한으로 실행**합니다. (다른 위치에 설치했다면 `update.bat -Dir D:\\ERP`)

업데이트가 하는 일: 데이터베이스 백업 → 서버 멈춤 → 프로그램·화면·화면 정의 교체 → 서버 시작 → 확인.
새 버전이 올라오지 않거나 화면 정의가 하나라도 받아들여지지 않으면 **이전 프로그램과 백업으로 자동으로 되돌립니다.**
어느 버전에서든 이 팩 하나로 올릴 수 있습니다(중간 버전을 거칠 필요 없음). 설치된 것보다 오래된 팩은 거절합니다(`-Force` 로 일부러 되돌릴 수 있음).
""") + """
## 건드리지 않는 것

운영에서 입력한 자료, 첨부 파일, 사용자, 역할, 권한, 시스템 설정(이름·로고·테마)은 업데이트해도 그대로입니다.
팩에 없는 화면(개발에서 지운 화면)은 자료 보호를 위해 운영에 그대로 남습니다.

## 설치된 뒤 (설치 폴더에서)

- 백업: `backup.bat` → `backups` 폴더에 파일 하나 (자료·첨부·사용자·권한 전부)
- 되돌리기: `restore.bat backups\\<파일>` (관리자 권한)
- 서비스 내리기: `uninstall.bat` (자료는 지우지 않음)
- 서버 기록: `logs` 폴더 · 데이터베이스 기록: `data\\pg\\log` 폴더
- 설정(포트, 서비스 이름, DB 비밀번호): `config.json` (관리자만 읽을 수 있음)

## 들어 있는 것

- `app\\app.jar` 서버 프로그램 · `web\\` 화면 · `release\\` 화면 정의, 공통 코드, 메뉴 편성 · `VERSION.json`
- `scripts\\` 설치·업데이트·백업 스크립트 (PowerShell)""" + ("""
- `runtime\\jre` 자바 17 (Eclipse Temurin) · `runtime\\pgsql` PostgreSQL {postgres} · `runtime\\winsw.exe` 서비스 등록 도구 · `runtime\\vc_redist.x64.exe` Visual C++ 런타임
""".format(postgres=version.get('postgres', '17')) if first else "\n")


def vendor(cache, fetch=True):
    """The Windows runtime pieces, downloaded once into the cache. Returns their paths (pgsql: the zip and its version)."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)

    def get(url, target):
        if not fetch:
            raise RuntimeError(f'{target.name} 이(가) 없습니다.')
        part = target.with_suffix(target.suffix + '.part')
        result = subprocess.run(['curl', '-fsSL', '-m', '1800', '-o', str(part), url], capture_output=True, text=True)
        if result.returncode != 0 or not part.is_file() or part.stat().st_size < 1_000_000:
            part.unlink(missing_ok=True)
            raise RuntimeError(f'{target.name} 을(를) 내려받지 못했습니다: {result.stderr[-200:]}')
        part.rename(target)
    out = {}
    for key, name in VENDOR_FILES.items():
        out[key] = cache / name
        if not out[key].is_file():
            get(SOURCES[name], out[key])
    held = sorted(cache.glob('pgsql-*.zip'))
    if not held:
        for version in POSTGRES_VERSIONS:
            try:
                get(SOURCES['pgsql'].format(version=version), cache / f'pgsql-{version}.zip')
                break
            except RuntimeError:
                continue
        held = sorted(cache.glob('pgsql-*.zip'))
        if not held:
            raise RuntimeError('PostgreSQL 윈도우 배포본을 내려받지 못했습니다.')
    out['pgsql'] = held[-1]
    out['postgres'] = held[-1].stem.split('-', 1)[1]
    return out


def runtime(cache):
    """runtime/ as it goes into the install pack, unpacked once: the JRE, PostgreSQL without its documentation, headers and pgAdmin."""
    pieces = vendor(cache)
    prepared = Path(cache) / f"runtime-{pieces['postgres']}"
    if (prepared / 'done').is_file():
        return prepared, pieces['postgres']
    shutil.rmtree(prepared, ignore_errors=True)
    (prepared / 'jre').mkdir(parents=True)
    with zipfile.ZipFile(pieces['jre']) as archive:
        for item in archive.infolist():
            rest = item.filename.split('/', 1)[1] if '/' in item.filename else ''
            if not rest or item.is_dir():
                continue
            target = prepared / 'jre' / rest
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))
    with zipfile.ZipFile(pieces['pgsql']) as archive:
        for item in archive.infolist():
            parts = item.filename.split('/')
            if item.is_dir() or len(parts) < 2 or parts[0] != 'pgsql':
                continue
            if parts[1] not in ('bin', 'lib', 'share') and not (len(parts) == 2 and parts[1].endswith('license.txt') and 'pgAdmin' not in parts[1]):
                continue
            if parts[1] == 'bin' and parts[-1].lower().startswith(('stackbuilder', 'pgadmin')):
                continue
            target = prepared.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))
    shutil.copy2(pieces['winsw'], prepared / 'winsw.exe')
    shutil.copy2(pieces['vc'], prepared / 'vc_redist.x64.exe')
    for needed in ('jre/bin/java.exe', 'pgsql/bin/initdb.exe', 'pgsql/bin/pg_ctl.exe', 'pgsql/bin/psql.exe', 'pgsql/bin/pg_dump.exe', 'pgsql/bin/pg_restore.exe', 'pgsql/bin/pg_isready.exe', 'pgsql/share/postgresql.conf.sample'):
        if not (prepared / needed).is_file():
            raise RuntimeError(f'런타임에 {needed} 이(가) 없습니다.')
    (prepared / 'done').write_text('ok')
    return prepared, pieces['postgres']


def check_scripts(folder, pwsh):
    """Parse every script with PowerShell's own parser (this machine cannot run them: they are for Windows). Returns the problems found."""
    if not pwsh or not Path(pwsh).is_file():
        return None
    command = ("$bad = @(); Get-ChildItem -Path '" + str(folder) + "' -Filter *.ps1 | ForEach-Object { $errors = $null; $tokens = $null; "
               "[void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$errors); "
               "foreach ($e in $errors) { $bad += ($_.Name + ':' + $e.Extent.StartLineNumber + ' ' + $e.Message) } }; $bad -join \"`n\"")
    result = subprocess.run([str(pwsh), '-NoLogo', '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=120)
    return [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]


def write_zips(layer, version, cache, target, name, pwsh=None, service='ERP', title=None):
    """Make <name>-install.zip and <name>-update.zip from the application layer (a folder with app/, web/, release/).
    Returns {'install': path, 'update': path, 'postgres': version, 'script_check': problems or None}."""
    layer, target = Path(layer), Path(target)
    prepared, postgres = runtime(cache)
    version = dict(version, postgres=postgres, platform='windows-x64', service=service, project=title or service)
    stage = target / f'{name}-scripts'
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    for file, text in SCRIPTS.items():       # UTF-8 with a byte order mark, Windows line ends; the project's name as the default folder and service name
        text = text.replace("[string]$Name = 'ERP'", f"[string]$Name = '{service}'").replace('-Name ERP2', f'-Name {service}2').replace(':\\ERP', f':\\{service}')
        (stage / file).write_bytes(b'\xef\xbb\xbf' + text.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8'))
    problems = check_scripts(stage, pwsh)
    if problems:
        raise RuntimeError('설치 스크립트 문법 오류: ' + '; '.join(problems[:5]))
    out = {'postgres': postgres, 'script_check': problems}
    for kind in ('install', 'update'):
        path = target / f'{name}-{kind}.zip'
        root = f'{name}-{kind}'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            def add(source, inside):
                source = Path(source)
                for file in sorted(source.rglob('*')) if source.is_dir() else [source]:
                    if file.is_file():
                        archive.write(file, f'{root}/{inside}/{file.relative_to(source)}' if source.is_dir() else f'{root}/{inside}')
            for part in ('app', 'web', 'release'):
                add(layer / part, part)
            add(stage, 'scripts')
            archive.writestr(f'{root}/VERSION.json', __import__('json').dumps(dict(version, kind=kind), ensure_ascii=False, indent=1))
            archive.writestr(f'{root}/README.md', readme(version, kind))
            for bat, script in (('update.bat', 'update.ps1'), ('backup.bat', 'backup.ps1'), ('restore.bat', 'restore.ps1'), ('uninstall.bat', 'uninstall.ps1')):
                archive.writestr(f'{root}/{bat}', _bat(script))
            if kind == 'install':
                archive.writestr(f'{root}/install.bat', _bat('install.ps1'))
                for file in sorted(prepared.rglob('*')):
                    if file.is_file() and file.name != 'done':
                        archive.write(file, f'{root}/runtime/{file.relative_to(prepared)}')
        out[kind] = path
    shutil.rmtree(stage, ignore_errors=True)
    return out
