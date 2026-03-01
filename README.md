This is my fork of Korni92s RNS-E-Hudiy, featuring a lot of cool features and a lot more vibecoding. ymmv. 

Features - 
DIS Service
  Displays navigation, now playing and phone info from hudiys api. 
  Defaults to now playing, automatically switches to navigation when it is started. Automatically switches to navigation when ~200m from a manuever, then returns back to previous tab 5s after the direction changes.
Hudiy DataView
  A cool UI to view various real time data on a set of cool dashboards for the Engine, Transmission and AWD. 
  Also includes a diagnostics page for pulling/clearing codes on modules, and viewing specific measuring groups for them.
  Functions over VW transport/diagnostics. 
  Provides a shortcut toggle to stop all diagnostic activity for using VCDS/other diagnostic tools.
RNSE Inputs
  Handles the RNSE inputs and Steering Wheel Controls
Power management
  Provides GPIO shutdown and CANbus Listen Only on Igniton off, allows for using the Radio Amp Wake as wake signal for your Pi.
  Ignition shutdown is an option if you want that as well ig. 


Configuration -
  config.json provides configuration for a lot of this stuff. the install script also replaces several hudiy config files. use flag -u to skip replacing hudiy config files with install.sh. config.json only gets replaced if it does not exist.

  Branch sets what the update script/button in the hudiy menu pulls. "testing" pulls the latest code from main, "beta" pulls the latest beta or release tag, "release" pulls the latest release tag. 
  Can interface sets the socketcan interface used by the can handler for most can functions except diagnostics. Diag worker just uses can0 currently.
  ZMQ configures some of the ZMQ streams used for various things. Honestly this is probably fucked and half of my scripts are hard coded but its there, would not mess with.
  CAN Ids configures some of the IDs used by the script. 
  FIS_line/Media/Nav are unused. Ignition Status 2C3 is correct for TTs, iirc 271 for some other platforms.
  Features section provides the bulk of the configuration. Some of its actually used. 
  Listen only mode puts the can0 interface into listen only when ignition is off, otherwise activity keeps the radio awake.
  Road-side is used to determine roundabout icons to use and thats about it. Right uses counterclockwise icons, left uses clockwise.
  Speed and Ambient Temp units arent yet used, they should be self explanatory. Im an American, id like my speed and ambient temp in imperial. All other data is metric, and you are wrong if you want them any other way. 
  Navigation displays whatever units it gets from the hudiy_api. 
Installation - 
........
  GLHF. 

  


