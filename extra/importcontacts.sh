cd /home/pi/sensecap_m1
sudo python3 import_contacts.py --freq 869.618 --sf 8 --bw 62.5
sudo python3 /home/pi/sensecap_m1/meshpoint_lorawan/scripts/repair_neighbour_timestamps.py --apply   # fix 2024 timestamps
sudo python3 /home/pi/sensecap_m1/meshpoint_lorawan/scripts/backfill_meshcore_signal.py --apply       # fill freq/SF on old rows
#sudo python3 /home/pi/sensecap_m1/fix.py

