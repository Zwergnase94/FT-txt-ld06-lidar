#!/bin/sh
# Resets the AM335x MUSB USB host controller on TXT to clear VBUS_ERROR / inrush brownout trip
echo -n "musb-hdrc.1" > /sys/bus/platform/drivers/musb-hdrc/unbind
sleep 1
echo -n "musb-hdrc.1" > /sys/bus/platform/drivers/musb-hdrc/bind
