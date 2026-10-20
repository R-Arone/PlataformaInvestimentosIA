"""Windows notifications with a fixed app identity, no shell interpolation."""
import base64
import json
import os
import subprocess
import urllib.parse

APP_ID='AporteBrasil.Research'
SCRIPT=r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$taskNotice = [Console]::In.ReadToEnd() | ConvertFrom-Json
$taskKey = 'HKCU:\Software\Classes\AppUserModelId\AporteBrasil.Research'
if (!(Test-Path -LiteralPath $taskKey)) { New-Item -Path $taskKey -Force | Out-Null }
New-ItemProperty -LiteralPath $taskKey -Name DisplayName -Value 'Aporte Brasil' -PropertyType String -Force | Out-Null
New-ItemProperty -LiteralPath $taskKey -Name ShowInSettings -Value 1 -PropertyType DWord -Force | Out-Null
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotifier, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.NotificationSetting, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null
$taskXml = New-Object Windows.Data.Xml.Dom.XmlDocument
$taskXml.LoadXml('<toast activationType="protocol"><visual><binding template="ToastGeneric"><text></text><text></text></binding></visual></toast>')
$taskXml.DocumentElement.SetAttribute('launch', [string]$taskNotice.url)
$taskNodes = $taskXml.GetElementsByTagName('text')
$taskNodes.Item(0).InnerText = [string]$taskNotice.title
$taskNodes.Item(1).InnerText = [string]$taskNotice.body
$taskToast = [Windows.UI.Notifications.ToastNotification]::new($taskXml)
$taskToast.Tag = 'research'
$taskToast.Group = 'AporteBrasil'
$taskToast.ExpirationTime = [DateTimeOffset]::Now.AddHours(1)
$taskNotifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AporteBrasil.Research')
if ($null -ne $taskNotifier.Setting -and [int]$taskNotifier.Setting -ne 0) { throw 'Notificacoes do Windows desativadas para este aplicativo.' }
$taskNotifier.Show($taskToast)
[Console]::Write('submitted')
'''


def notify(title,body,url):
    if os.name!='nt':raise ValueError('Notificações nativas disponíveis no Windows.')
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.username or parsed.password:
        raise ValueError('O alerta deve abrir apenas o aplicativo local.')
    if not isinstance(title,str) or not isinstance(body,str):raise ValueError('Texto de alerta inválido.')
    # JSON goes through stdin. Headline text never becomes executable PowerShell.
    code=base64.b64encode(SCRIPT.encode('utf-16-le')).decode('ascii')
    executable=os.path.join(os.environ.get('SystemRoot',r'C:\Windows'),'System32','WindowsPowerShell','v1.0','powershell.exe')
    result=subprocess.run([executable,'-NoProfile','-NonInteractive','-WindowStyle','Hidden','-EncodedCommand',code],
        input=json.dumps({'title':title[:100],'body':body[:350],'url':url},ensure_ascii=False),
        capture_output=True,encoding='utf-8',errors='replace',timeout=20,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode or 'submitted' not in result.stdout:
        raise ValueError('O Windows não aceitou a notificação. Confira as notificações do Aporte Brasil nas configurações do sistema.')
    return {'submitted':True,'note':'O Windows recebeu o alerta; modo Não incomodar pode ocultar o popup.'}
