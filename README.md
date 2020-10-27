# Raspberry Pi Camera / Webcam streaming helper scripts

This script is designed to help automate turing a raspberry pi with a
compatible video4linux2 camera into a MPEG-DASH / HLS streaming server.

The steps it will attempt to take:

* Install FFmpeg OR (optional) Compile and Install FFmpeg ( with h264 hardware acceleration and nonfree libraries)
* Install nginx for DASH / HLS OR install RTSP server if desired
* (DASH/HLS) Update rc.local to run required setup script on reboot
* (DASH/HLS) Create index.html file to view video stream at
* Create systemd service and enable it

If you will be compiling while running over SSH, please use in a background terminal like "tmux" or "screen".

If you are compilng FFmpeg, be aware, this will build a NON REDISTRIBUTABLE FFmpeg.
You will not be able to share the built binaries under any license.

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

## Compile FFmpeg
If you want to compile FFmpeg make sure to pass the `--compile-ffmpeg` flag
and I suggest setting the user to `pi` if making in your home directory. 

```
sudo python3 streaming_setup.py --compile-ffmpeg --run-as pi
```




## Script Options 

```
usage: streaming_setup [-h] [-v] [-d DEVICE] [-s VIDEO_SIZE] [-f INPUT_FORMAT]
                       [-c CODEC] [--ffmpeg-params FFMPEG_PARAMS]
                       [--index-file INDEX_FILE]
                       [--on-reboot-file ON_REBOOT_FILE]
                       [--systemd-file SYSTEMD_FILE] [--compile-ffmpeg]
                       [--camera-info] [--minimal] [--run-as RUN_AS]
                       [--disable-fdk-aac] [--disable_avisynth]
                       [--disable-dav1d] [--disable-zimg] [--disable-kvazaar]
                       [--disable-libxavs] [--disable-libsrt] [--rebuild-all]
                       [--safe]

streaming_setup version 1.4.0

optional arguments:
  -h, --help            show this help message and exit
  -v, --version
  -d DEVICE, -i DEVICE, --device DEVICE
                        Camera. Selected: /dev/video0
  -s VIDEO_SIZE, --video-size VIDEO_SIZE
                        The video resolution from the camera (using 2592x1944)
  -f INPUT_FORMAT, --input-format INPUT_FORMAT
                        The format the camera supports (using h264)
  -c CODEC, --codec CODEC
                        Conversion codec (using 'copy')
  --ffmpeg-params FFMPEG_PARAMS
                        specify additional FFmpeg params, helpful if not
                        copying codec e.g.: '-b:v 4M -maxrate 4M -bufsize 8M'
  --index-file INDEX_FILE
  --on-reboot-file ON_REBOOT_FILE
  --systemd-file SYSTEMD_FILE
  --compile-ffmpeg
  --camera-info         Show all detected cameras [/dev/video(0-9)] and exit
  --minimal             Minimal FFmpeg compile including h264, x264, alsa
                        sound and fonts
  --run-as RUN_AS       compile programs as provided user (suggested 'pi',
                        defaults to 'root')
  --disable-fdk-aac     Normally installed on full install
  --disable_avisynth    Normally installed on full install
  --disable-dav1d       Normally installed on full install
  --disable-zimg        Normally installed on full install
  --disable-kvazaar     Normally installed on full install
  --disable-libxavs     Normally installed on full install
  --disable-libsrt      Normally installed on full install
  --rebuild-all         Recompile all libraries
  --safe                disable overwrite of existing or old scripts
```

## License

MIT License - Copyright (c) 2020 Chris Griffith
