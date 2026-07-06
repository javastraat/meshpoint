# MeshCore Sniffer — Makefile
#
# sx1302_hal cloned into this directory
LORAGW_PATH = $(CURDIR)/sx1302_hal

CC      = gcc
CFLAGS  = -Wall -Wextra -O2 -I$(LORAGW_PATH)/libloragw/inc -I$(LORAGW_PATH)/libtools/inc
LDFLAGS = -L$(LORAGW_PATH)/libloragw -L$(LORAGW_PATH)/libtools \
          -lloragw -ltools -lm -lpthread -lusb-1.0 -lcrypto

TARGET  = sniffer
SRC     = sniffer.c

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(SRC)
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)
	@echo "Built: ./$(TARGET)"
	@echo "Run:   sudo ./$(TARGET)"

clean:
	rm -f $(TARGET)
