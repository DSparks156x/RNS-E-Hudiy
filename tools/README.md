Tools you might need to modify the scripts or files.

1. bitmap_tool.html
  -  It translates a bitmap to add it to icons.py
2. theme_viewer.html
  - Displays a light/dark mode theme spit out from hudiy, useful for assigning various color variables to things with a reference.
3. 
   process_dumps.py
  - takes in a text file with a candump and removes various known things, and shows changing data.
  - candump can0 > candump.txt
  - python3 process_dumps.py candump194f.txt
  - sample decode.txt is idling at oil temp ~194f. 
4.
  status_tp2_logger.py - moved to tp2 folderas it will be ran primarily on Pi, and tp2 folder is updated by installer.
  - configure a module, groups, and ids and it will save the last values each time you press enter. used for helping correlate Data in status messages to "ground truth" tp2 measuring groups. currently goes off infotainment can, will likely add interface as a flag... could be genuinely useful for decoding say powertrain messages if you had a powertrain interface. flags docs need to be updated but i dont feel like it. 
  - python3 status_tp2_logger.py -m 1 -g 1,2,3 -i 1,2,3
5.
  can_decoder_pro.py
  - takes in a text file with a status_tp2_logger log and tries to correlate CAN IDs and bit positions to TP2 fields
  - python3 can_decoder_pro.py decoder.txt
  - provides correlation between groups and specific bytes /formulas 
  - not great, not terrible, could be improved, data isnt really time synced and i didnt give it many samples so it did p good.
6.
  dhu_driver.py
  - python3 dhu_driver.py
  - targets the default location of the DHU, if you installed it elsewhere, you'll need to modify the script.
  - targets default.ini config, will need [sensors] location = true
  - drives the DHU coordinate location and heading with keyboard inputs, used for testing nav and other features without a real car.
  - W/S to accelerate/decelerate, A/D to steer, Space to brake, R to reset to start position, Q to quit
  - passes args straight to DHU.
  - used for figuring out some of how nav works. thats about it. not super useful but i made it so its in this repo. 
