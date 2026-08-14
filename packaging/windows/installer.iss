; Inno Setup starting point. Build only after a clean-machine test of dist/BiliLotteryAssistant.
[Setup]
AppName=BiliLotteryAssistant
AppVersion=0.1.1
DefaultDirName={autopf}\BiliLotteryAssistant
DefaultGroupName=BiliLotteryAssistant
OutputDir=output
OutputBaseFilename=BiliLotteryAssistant-Setup-0.1.1
Compression=lzma
SolidCompression=yes

[Files]
Source: "..\..\dist\BiliLotteryAssistant\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\BiliLotteryAssistant"; Filename: "{app}\BiliLotteryAssistant.exe"
