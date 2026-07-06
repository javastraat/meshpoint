#!/bin/bash
# Reset the Sencap M1 / SX1303 concentrator via GPIO23
# Run this before starting the sniffer.

GPIO_RESET=23
GPIO_POWER=18

# Export GPIOs if not already
for pin in $GPIO_RESET $GPIO_POWER; do
    [ -d /sys/class/gpio/gpio${pin} ] || echo $pin > /sys/class/gpio/export
    echo "out" > /sys/class/gpio/gpio${pin}/direction
done

# Power on
echo "1" > /sys/class/gpio/gpio${GPIO_POWER}/value
sleep 0.1

# Reset pulse
echo "1" > /sys/class/gpio/gpio${GPIO_RESET}/value
sleep 0.1
echo "0" > /sys/class/gpio/gpio${GPIO_RESET}/value
sleep 0.1
echo "1" > /sys/class/gpio/gpio${GPIO_RESET}/value
sleep 0.1

echo "M1 reset done."
