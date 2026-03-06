## DIS Stuff
* Nav Screen Fixes
Nav Screen description scroll clearing needs to be fixed. (causes ghost text)
Distance display "centering" needs to be removed. left aligned in current pos is fine. centering proportional font is hard.
Nav distance bar rendering wacky. probably could also be scaled dif (start further away)
Nav auto switch should happen further away. 
Nav auto switch return no longer works. 
* Nav Screen Improvements
Add white flash on auto switch to catch attention about upcoming direction.
Add arrival time? would need to be added to hudiy api
* Car info screen Fixes/Improvements
Fix boost dispay - probably remove decimals?
Fix Load/IAT decoding
Add coolant to last line? 
Refresh rate could be increased - status messages are much faster.. unsure of practical DIS limits
* General DIS improvements
DIS service should report current status on command handling (Still sending/vs committed)
DIS display would then wait for commit before updating active screen and sending new payload.... this would allow dropping display updates instead of piling up a backlog and falling behind. 
* Add top lines to dis display
I would likely retain ambient temp in the second line. 
First line could be used for upcoming nav direction if active on another screen? perhaps direction + truncated description + distance? or only parts of that. could be used in second line alongside ambient? 
Nav screen could have current track title in first line? maybe artist + ambinet second? 
Car info could display track stuff, or nav if its active perhaps? or cycle. lots of options

## Dataview Stuff
* UI overall scaling could be improved.. works fine on 800x480 down to 800x400, could/should generally be made more responsive though.
* Diagnostics measuring blocks size needs to be fixed. wayy too large currently.
* Diagnostics measuring blocks should only show first 4 blocks. Some groups have 8, but most of them are just undocumented status's. not really useful to show them. 

## Diagnostic/TP2 Backend stuff.
* DTC functionality only works on some modules (ECU, transmission), others reject/fail. (ABS, HVAC). They likely need a dif protocol or something. 
* May generally be possible to make a bit faster
* Configurable CAN interface would be nice.. Currently don't see a reason not to just use infotainment can, but maybe possible to pull a bit faster? could be other undiscovered restrictions. 10 read/s with test script feels like a module hard limit though.
* Poorly named hudiy_status_service / can_service.py is currently responsible for handling the few powertrain status messages on infotainment bus.  It could be expanded to handle powertrain status messages on the powertrain bus if an interface were added. I currently have no need for this, but it would be a useful feature to have.
* Generally need to fix the decode of the current status messages/add more. Boost works, but formula is slightly off. Load/IAT are wrong. Coolant temp is either a wierd sensor or wrong. 
* Several measuring group units need to be fixed. Transmission torque, valve current, awd torque, awd pressure, several other awd status probably. Injection time possibly slightly wrong. 

## Bigger features to possibly add.
* Terminal app. would have shortcut in menu. Unsure wether hudiy supports non webview apps, if not it could easily be a webview app + backend service. 
* Data logging. Could be within dataview, could be a new app.  Could log in vcds format, or more standard csv format (like datazap supports).
Perhaps have some presets for common value sets, or manual selection of groups/modules. 
Multi module logging could be cool, would you want seperate or combined files though? 
* 0-60 timing would be cool. lots of possibilites for this though. Should it be in dataview? should it be in the cluster? should it just use vehicle speed from can status messages? Should it also support a GPS module on the pi?

## Smaller uncategorized
Steering wheel PTT button. would be cool to use for assistant activation. Not sure this is on canbus, plus other modules use it. Dont remember wether nav or telephone use it. Telephone id pull the fuse on anyways. 