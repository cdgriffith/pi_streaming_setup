# Raspberry Pi Camera / Webcam streaming helper scripts

This script is designed to help automate turing a raspberry pi with a
compatible video4linux2 camera into a MPEG-DASH / HLS / RTSP streaming server.

The steps it will attempt to take:

* Install FFmpeg
* Install nginx for DASH / HLS OR install RTSP server if desired
* (DASH/HLS) Update rc.local to run required setup script on reboot
* (DASH/HLS) Create index.html file to view video stream at
* Create systemd service and enable it

This script requires Python 3.6+

## Grab the script

```
curl -O https://raw.githubusercontent.com/cdgriffith/pi_streaming_setup/master/streaming_setup.py
```

You could also clone the repo, or use wget, or whatever you desire. You just need the `streaming_setup.py` file.


## MPEG DASH / HLS

DASH is a great way to use your device as standalone streaming server with a easy to view webpage hosted on the Pi.
The disadvantage is the delay due to buffering and the way DASH / HLS work with manifest files. You will have a 5~20
second lag from the camera to when you view it.

To use the pre-built FFmpeg and MPEG DASH, just need to run the script as root / sudo then you're good to go:

```
sudo python3 streaming_setup.py
```

## RTSP

If you want near instant real time streaming, it's best to use the aptly named Real Time Streaming Protocol, RTSP.

```
sudo python3 streaming_setup.py --rtsp
```

If you are connecting to an external RTSP server, pass in the `rtsp-url` argument.

```
sudo python3 streaming_setup.py --rtsp --rtsp-url rtsp://192.168.1.123:8554/raspberrypi
```

## Streaming Setup Script Options

```
sudo python streaming_setup.py --help
usage: streaming_setup [-h] [-v] [--ffmpeg-command] [-d DEVICE] [-s VIDEO_SIZE] [-r] [--rtsp-url RTSP_URL] [-f INPUT_FORMAT] [-b BITRATE] [-c CODEC] [--ffmpeg-params FFMPEG_PARAMS]
                       [--index-file INDEX_FILE] [--on-reboot-file ON_REBOOT_FILE] [--systemd-file SYSTEMD_FILE] [--camera-info] [--minimal] [--safe]

streaming_setup version 1.8

optional arguments:
  -h, --help            show this help message and exit
  -v, --version
  --ffmpeg-command      print the automated FFmpeg command and exit
  -d DEVICE, -i DEVICE, --device DEVICE
                        Camera. Selected: /dev/video0
  -s VIDEO_SIZE, --video-size VIDEO_SIZE
                        The video resolution from the camera (using 1280x720)
  -r, --rtsp            Use RTSP instead of DASH / HLS
  --rtsp-url RTSP_URL   Provide a remote RTSP url to connect to and don't set up a local server
  -f INPUT_FORMAT, --input-format INPUT_FORMAT
                        The format the camera supports (using mjpeg)
  -b BITRATE, --bitrate BITRATE
                        Streaming bitrate, is auto calculated by default. (Will be ignored if the codec is 'copy')
  -c CODEC, --codec CODEC
                        Conversion codec (using 'h264_v4l2m2m')
  --ffmpeg-params FFMPEG_PARAMS
                        specify additional FFmpeg params, MUST be doubled quoted! helpful if not copying codec e.g.: '"-b:v 4M -maxrate 4M -g 30 -num_capture_buffers 128"'
  --index-file INDEX_FILE
  --on-reboot-file ON_REBOOT_FILE
  --systemd-file SYSTEMD_FILE
  --camera-info         Show all detected cameras [/dev/video(0-9)] and exit
  --safe                disable overwrite of existing or old scripts
```

## Compile FFmpeg
If you want to compile FFmpeg you will need to grab the `compile_ffmpeg.py` file.

> This will take hours on most Raspberry Pi devices!

Note: THERE IS NO NEED TO COMPILE FFMPEG YOURSELF IN MOST CASES. ONLY DO IT IF YOU KNOW YOU NEED AN UNUSUAL ENCODER.

```
curl -O https://raw.githubusercontent.com/cdgriffith/pi_streaming_setup/master/compile_ffmpeg.py
```

I suggest setting the user to `pi` if making in your home directory.

```
sudo python3 compile_ffmpeg.py --run-as pi
```

If you will be compiling while running over SSH, please use in a background terminal like "tmux" or "screen".

Adding `--install` it will install it to `/usr/local/bin/ffmpeg`. You can always do this later yourself by
going into the `FFmpeg` folder and typing `make install`

If you are compiling FFmpeg, be aware, this will build a NON-REDISTRIBUTABLE FFmpeg.
You will not be able to share the built binaries under any license.

## License

MIT License - Copyright (c) 2020-2025 Chris Griffith

## Debuging

### Error: ioctl(VIDIOC_STREAMON) failure : 1, Operation not permitted

Go into raspi-config and up the video memory (memory split) to 256 and reboot. (thanks to #15 [rezrov](https://github.com/cdgriffith/pi_streaming_setup/issues/15))

## Major Changes

### 1.8

* Adding check for existing ffmpeg ahead of time (thanks to Noah Abu-Hajar)
* Fix download for mediamtx (thanks to Christopher Brown)

### 1.7

* Adding support for 64-bit OSes (aarch64)
* Changing default codec to h264_v4l2m2m (removing h264_omx)
* Splitting out compile_ffmpeg.py into its own file
