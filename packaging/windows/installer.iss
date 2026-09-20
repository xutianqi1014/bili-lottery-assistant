; Inno Setup starting point. Build only after a clean-machine test of dist/BiliLotteryAssistant.
[Setup]
AppName=BiliLotteryAssistant
AppVersion=1.6.0
DefaultDirName={autopf}\BiliLotteryAssistant
DefaultGroupName=BiliLotteryAssistant
OutputDir=output
OutputBaseFilename=BiliLotteryAssistant-Setup-1.6.0
Compression=lzma
SolidCompression=yes

[Files]
Source: "..\..\dist\v1.6.0\BiliLotteryAssistant\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\BiliLotteryAssistant"; Filename: "{app}\BiliLotteryAssistant.exe"
