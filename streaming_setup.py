#!/usr/bin/env python3
"""
This script is designed to help automate turing a raspberry pi with a
compatible video4linux2 camera into a MPEG-DASH / HLS streaming server.

The steps it will attempt to take:

* Install nginx
* Compile and Install FFmpeg with h264 hardware acceleration via h264_omx (optional)
* Update rc.local to run required setup script on reboot
* Create index.html file to view video stream at
* Create encode_webcam systemd service and enable it

If running over SSH, please use in a background terminal like "tmux" or "screen" due to compile time.
"""
import logging
import os
import sys
from subprocess import run
from pathlib import Path
from argparse import ArgumentParser

__author__ = "Chris Griffith"
__version__ = "1.0.0"

log = logging.getLogger("streaming_setup")
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)-12s  %(levelname)-8s %(message)s")

here = Path(__file__).parent
disable_overwrite = False


def parse_arguments():
    video_devices = list(Path("/dev/").glob("video*"))
    default_video_device = str(video_devices[0]) if video_devices else "/dev/video0"

    parser = ArgumentParser(prog="streaming_setup", description=f"streaming_setup version {__version__}")
    parser.add_argument("-v", "--version", action="store_true")
    parser.add_argument("-d", "-i", "--device", default=default_video_device)
    parser.add_argument("-s", "--video-size", default="1920x1080")
    parser.add_argument("-f", "--input-format", default="h264")
    parser.add_argument("--index-file", default="/var/www/html/index.html")
    parser.add_argument("--on-reboot-file", default="/opt/setup_streaming.sh")
    parser.add_argument("--systemd-file", default="/etc/systemd/system/encode_webcam.service")
    parser.add_argument("--disable-compile-ffmpeg", action="store_true")
    parser.add_argument("--disable-install-ffmpeg", action="store_true")
    parser.add_argument( "--safe", action="store_true", help="disable overwrite of existing scripts.")
    return parser.parse_args()


def cmd(command, cwd=here):
    result = run(command, shell=True, cwd=cwd)
    result.check_returncode()
    return result


def program_installations(compile_ffmpeg, install_ffmpeg):
    log.info("Installing nginx")
    cmd("apt install -y nginx")

    if compile_ffmpeg:
        if (here / "FFmpeg" / "ffmpeg").exists():
            log.info(f"FFmpeg is already compiled at {here / 'FFmpeg' / 'ffmpeg'}")
            if install_ffmpeg:
                install_compiled_ffmpeg()
            return
        log.info("Installing FFmpeg requirements")
        cmd(
            "apt install -y git checkinstall build-essential libomxil-bellagio-dev "
            "libfreetype6-dev libmp3lame-dev libx264-dev fonts-freefont-ttf libasound2-dev"
        )

        if not (here / "FFmpeg").exists():
            log.info("Grabbing FFmpeg")
            cmd("git clone https://github.com/FFmpeg/FFmpeg.git --depth 1")

        log.info("Configuring FFmpeg")
        cmd(
            "./configure --arch=armel --target-os=linux --enable-gpl --enable-omx --enable-omx-rpi "
            "--enable-libfreetype --enable-libx264 --enable-libmp3lame --enable-mmal"
            " --enable-indev=alsa --enable-outdev=alsa",
            cwd=here / "FFmpeg",
        )

        log.info("Building FFmpeg (This will take a while)")
        cmd("make -j4", cwd=here / "FFmpeg")
        if install_ffmpeg:
            install_compiled_ffmpeg()


def install_compiled_ffmpeg():
    log.info("Installing FFmpeg")
    cmd("apt purge ffmpeg -y")
    cmd("checkinstall --pkgname=ffmpeg -y", cwd=here / "FFmpeg")
    cmd("apt-mark hold ffmpeg")
    cmd('echo "ffmpeg hold" | sudo dpkg --set-selections')


def update_rc_local_file(on_reboot_file):
    rc_local_update = [
        "# Streaming Shared Memory Setup",
        f"if [ -f {on_reboot_file} ]; then",
        f"    /bin/bash {on_reboot_file} || true",
        "fi",
    ]

    rc_local_file = Path("/etc/rc.local")
    contents = rc_local_file.read_text().splitlines()  # Don't strip, need to make sure `exit 0` is at root level
    if "# Streaming Shared Memory Setup" in contents:
        log.info(f"rc.local already calls {on_reboot_file}, not updating")
        return
    exit_location = contents.index("exit 0")
    if exit_location > 0:
        log.info("rc.local: Found proper location to add info to rc.local file")
        output = contents[:exit_location] + rc_local_update + contents[exit_location:]
    else:
        if disable_overwrite:
            log.warning(f"Could not figure out safe way to update {rc_local_file}!")
            return
        log.warning(
            f"Could not find usual spot in {rc_local_file} file, adding to end of file,"
            " please make sure it is correct!"
        )
        output = contents + rc_local_update
    rc_local_file.write_text("\n".join(output))


def install_index_file(index_file, video_size):
    width, height = video_size.split("x")
    width, height = int(width), int(height)
    if width > 1920:
        difference = width / 1920
        width = 1920
        height = height * difference

    index_contents = f"""<!DOCTYPE html>
<head>
    <meta charset="UTF-8">
    <style>
        video {{
            max-width: {width}px;
            max-height: {height}px;
        }}
    </style>
</head> 
<body>
    <div id="main">
        <video data-dashjs-player autoplay controls src="manifest.mpd" type="application/dash+xml"></video>
    </div>
    <script src="https://cdn.dashjs.org/latest/dash.all.min.js"></script>
</body>
</html>
"""
    if index_file.exists():
        if disable_overwrite:
            log.info(f"File {index_file} already exists. Not overwriting with: \n{index_file}")
            return
        log.warning(f"Index file exists at {index_file}, overwriting")
    index_file.write_text(index_contents)
    index_file.chmod(0o644)


def install_on_reboot_file(on_reboot_file, index_file):
    on_reboot_contents = f"""mkdir -p /dev/shm/streaming
if [ ! -e /var/www/html/streaming ]; then
    ln -s  /dev/shm/streaming /var/www/html/streaming
fi 
if [ ! -e /var/www/html/streaming/index.html ]; then
    ln -s {index_file} /var/www/html/streaming/index.html
fi 
"""
    if on_reboot_file.exists():
        if disable_overwrite:
            log.info(f"File {on_reboot_file} already exists. Not overwriting with: \n{on_reboot_file}")
            return
        log.warning(f"On reboot file exists at {on_reboot_file}, overwriting")
    on_reboot_file.write_text(on_reboot_contents)
    on_reboot_file.chmod(0o755)


def install_systemd_file(systemd_file, input_format, video_size, video_device):
    systemd_contents = f"""# /etc/systemd/system/encode_webcam.service
[Unit]
Description=encode_webcam
After=network.target rc-local.service

[Service]
Restart=always
RestartSec=20s
ExecStart=ffmpeg -f v4l2 -input_format {input_format} -s {video_size} -i {video_device} -c:v copy -seg_duration 0.2 -remove_at_exit 1 -window_size 10 -f dash -hls_playlist 1 /dev/shm/streaming/manifest.mpd

[Install]
WantedBy=multi-user.target
"""

    if systemd_file.exists():
        if disable_overwrite:
            log.info(f"File {systemd_file} already exists. Not overwriting with: \n{systemd_file}")
            return
        log.warning(f"Systemd file exists at {systemd_file}, overwriting")
    systemd_file.write_text(systemd_contents)
    systemd_file.chmod(0o755)


def start_services(on_reboot_file):
    cmd(f"/bin/bash {on_reboot_file}")
    cmd("systemctl daemon-reload")
    cmd("systemctl start encode_webcam")
    cmd("systemctl enable encode_webcam")


def main():
    global disable_overwrite
    args = parse_arguments()
    if args.version:
        print(f"{__version__}")
        return

    if os.geteuid() != 0:
        log.critical("This script requires root / sudo privileges")
        sys.exit(1)

    index_file = Path(args.index_file)
    on_reboot_file = Path(args.on_reboot_file)
    systemd_file = Path(args.systemd_file)
    if args.safe:
        disable_overwrite = True

    program_installations(not args.disable_compile_ffmpeg, not args.disable_install_ffmpeg)
    update_rc_local_file(on_reboot_file=on_reboot_file)
    install_index_file(index_file=index_file, video_size=args.video_size)
    install_on_reboot_file(on_reboot_file=on_reboot_file, index_file=index_file)
    install_systemd_file(
        systemd_file=systemd_file,
        input_format=args.input_format,
        video_size=args.video_size,
        video_device=args.device,
    )


if __name__ == "__main__":
    main()
