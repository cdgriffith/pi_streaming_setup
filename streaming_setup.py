#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
This script is designed to help automate turing a raspberry pi with a
compatible video4linux2 camera into an MPEG-DASH / HLS streaming server.

The steps it will attempt to take:

* Install nginx
* Install FFmpeg OR
* Update rc.local to run required setup script on reboot
* Create index.html file to view video stream at
* Create systemd service and enable it


The MIT License

Copyright (c) 2020-2023 Chris Griffith

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import logging
import os
import sys
import shutil
import datetime
import json
from subprocess import run, CalledProcessError, PIPE, STDOUT, Popen
from pathlib import Path
from argparse import ArgumentParser

__author__ = "Chris Griffith"
__version__ = "1.7.1"

log = logging.getLogger("streaming_setup")
command_log = logging.getLogger("streaming_setup.command")
CMD_LVL = 15
logging.addLevelName(CMD_LVL, "CMD")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)-12s  %(levelname)-8s %(message)s",
    filename=f"streaming_setup_{datetime.datetime.now().strftime('%Y%M%d_%H%M%S')}.log",
)

sh = logging.StreamHandler(sys.stdout)
log.setLevel(logging.DEBUG)
command_log.setLevel(logging.DEBUG)
log.addHandler(sh)

here = Path(__file__).parent
disable_overwrite = False
rebuild_all = False
warn_no_camera = False
detected_arch = None
detected_model = ""
detected_cores = 1

class ffmpeg_arguments_defaults_set(object):
    def __init__(self, input_format, video_size, device, codec):
        self.input_format=input_format
        self.video_size=video_size
        self.device=device
        self.codec=codec

def parse_arguments():
    ffmpeg_argument_help_prefix = "example:"

    if ffmpeg_installed():
        ffmpeg_argument_help_prefix = "using:"

    device, fmt, resolution = find_best_device()
    codec = "copy" if fmt == "h264" else "h264_v4l2m2m"

    default_device=str(device)
    default_video_size=resolution
    default_input_format=fmt
    default_codec=codec

    parser = ArgumentParser(prog="streaming_setup", description=f"streaming_setup version {__version__}")
    parser.add_argument("-v", "--version", action="store_true")
    parser.add_argument("--ffmpeg-command", action="store_true", help="print the automated FFmpeg command and exit")
    parser.add_argument("-d", "-i", "--device", default=default_device, help=f"Camera. {ffmpeg_argument_help_prefix} '{device}'")
    parser.add_argument(
        "-s", "--video-size", default=default_video_size, help=f"The video resolution from the camera ({ffmpeg_argument_help_prefix} '{resolution}')"
    )
    parser.add_argument("-r", "--rtsp", action="store_true", help="Use RTSP instead of DASH / HLS")
    parser.add_argument(
        "--rtsp-url", default="", help="Provide a remote RTSP url to connect to and don't set up a local server"
    )
    parser.add_argument("-f", "--input-format", default=default_input_format, help=f"The format the camera supports ({ffmpeg_argument_help_prefix} '{fmt}')")
    parser.add_argument(
        "-b",
        "--bitrate",
        default="dynamic",
        help=f"Streaming bitrate, is auto calculated by default." f" (Will be ignored if the codec is 'copy')",
    )
    parser.add_argument("-c", "--codec", default=default_codec, help=f"Conversion codec ({ffmpeg_argument_help_prefix} '{codec}')")
    parser.add_argument(
        "--ffmpeg-params",
        default="",
        help="specify additional FFmpeg params, MUST be doubled quoted! helpful "
        "if not copying codec e.g.: '\"-b:v 4M -maxrate 4M -g 30 -num_capture_buffers 128\"'",
    )
    parser.add_argument("--index-file", default="/var/lib/streaming/index.html")
    parser.add_argument("--on-reboot-file", default="/var/lib/streaming/setup_streaming.sh")
    parser.add_argument("--systemd-file", default="/etc/systemd/system/stream_camera.service")
    parser.add_argument(
        "--camera-info", action="store_true", help="Show all detected cameras [/dev/video(0-9)] and exit"
    )

    parser.add_argument("--safe", action="store_true", help="disable overwrite of existing or old scripts")

    parsed_arguments = parser.parse_args()

    return parsed_arguments, ffmpeg_arguments_defaults_set(parsed_arguments.input_format == default_input_format, 
                                                          parsed_arguments.video_size == default_video_size,
                                                          parsed_arguments.device == default_device,
                                                          parsed_arguments.codec == default_codec)

def set_ffmpeg_argument_defaults(args, ffmpeg_arguments_defaults_set):

    if (not ffmpeg_arguments_defaults_set.input_format 
        and not ffmpeg_arguments_defaults_set.video_size 
        and not ffmpeg_arguments_defaults_set.device 
        and not ffmpeg_arguments_defaults_set.codec):
        return

    device, fmt, resolution = find_best_device()
    codec = "copy" if fmt == "h264" else "h264_v4l2m2m"

    args.input_format=fmt if ffmpeg_arguments_defaults_set.input_format else args.input_format
    args.video_size=resolution if ffmpeg_arguments_defaults_set.video_size else args.video_size
    args.device=str(device) if ffmpeg_arguments_defaults_set.device else args.device
    args.codec=codec if ffmpeg_arguments_defaults_set.codec else args.codec

def cmd(command, cwd=here, env=None, **kwargs):
    environ = os.environ.copy()
    if env:
        environ.update(env)

    log.debug(f'Executing from "{cwd}" command: {command} ')
    process = Popen(command, shell=True, cwd=cwd, stdout=PIPE, stderr=STDOUT, env=environ, **kwargs)
    while True:
        output = process.stdout.readline().decode("utf-8").strip()
        if output == "" and process.poll() is not None:
            break
        command_log.log(CMD_LVL, output)
    return_code = process.poll()
    if return_code > 0:
        raise CalledProcessError(returncode=return_code, cmd=command)


def apt(command, cwd=here):
    try:
        return cmd(command, cwd)
    except CalledProcessError:
        cmd("apt update --fix-missing")
        return cmd(command, cwd)


def lscpu_output():
    results = json.loads(run("lscpu -J", shell=True, stdout=PIPE).stdout.decode("utf-8").lower())
    return {x["field"].replace(":", ""): x["data"] for x in results["lscpu"]}


def camera_info(device, hide_error=False):
    # ffmpeg -hide_banner -f video4linux2 -list_formats all -i /dev/video0
    # [video4linux2,v4l2 @ 0xf0cf70] Raw       :     yuyv422 :           YUYV 4:2:2 : {32-2592, 2}x{32-1944, 2}
    # [video4linux2,v4l2 @ 0xf0cf70] Compressed:       mjpeg :            JFIF JPEG : {32-2592, 2}x{32-1944, 2}

    # [video4linux2,v4l2 @ 0xf0cf70] Compressed:       mjpeg :          Motion-JPEG : {32-2592, 2}x{32-1944, 2}
    data = run(
        f"ffmpeg -hide_banner -f video4linux2 -list_formats all -i {device}", shell=True, stdout=PIPE, stderr=PIPE
    )
    stdout, stderr = data.stdout.decode("utf-8"), data.stderr.decode("utf-8")
    if "Not a video capture device" in stdout or "Not a video capture device" in stderr:
        if not hide_error:
            log.error(f"{device} is not a video capture device ")
        return

    def get_best_resolution(res):
        if "{" in res:
            # [video4linux2,v4l2 @ 0xf0cf70] Compressed:        h264 :                H.264 : {32-2592, 2}x{32-1944, 2}
            try:
                w, h = res.split("x")
                w = w[w.index("-") + 1 : w.index(",")]
                h = h[h.index("-") + 1 : h.index(",")]
                return f"{w}x{h}" if int(w) < 2000 else "1920x1080"
            except Exception:
                log.exception(f"Couldn't figure out resolution from: {res}")
        else:
            bw, bh = 0, 0
            for option in res.split():
                try:
                    w, h = option.split("x")
                    w, h = int(w), int(h)
                    if w * h > bw * bh:
                        bw, bh = w, h
                except Exception:
                    log.exception(f"Couldn't figure out resolution from: {option}")
            return f"{bw}x{bh}" if int(bw) < 2000 and bw else "1920x1080"

    supported_formats = {}
    for line in stderr.splitlines():
        if not line.startswith("[video4linux2") or line.count(": ") <= 2:
            continue
        try:
            _, fmt, _, resolution = line.split("]", 1)[1].split(": ")
        except ValueError as err:
            log.exception(f"Could not parse format line '{line}'")
            continue
        if fmt.strip() != "Unsupported":
            supported_formats[fmt.strip()] = get_best_resolution(resolution.strip())
    return supported_formats


def find_best_device():
    global warn_no_camera
    current_best = ("", {})
    for device in Path("/dev/").glob("video?"):
        options = camera_info(device, hide_error=True)
        if not options:
            continue
        if "h264" in options:
            current_best = (device, options)
        elif "h264" not in current_best[1]:
            current_best = (device, options)
    if not current_best[0]:
        warn_no_camera = True
        return "/dev/video0", "h264", "1920x1080"  # Assume user will connect pi camera
    for fmt in ("h264", "mjpeg", "yuyv422", "yuv420p"):
        if fmt in current_best[1]:
            return current_best[0], fmt, current_best[1][fmt]
    fmt, res = list(current_best[1].items())[0]
    return current_best[0], fmt, res


def all_cameras():
    for device in Path("/dev/").glob("video?"):
        print(f"{device} {camera_info(device, hide_error=True)}")


def install_nginx():
    log.info("Installing nginx")
    apt("apt install -y nginx")

def install_ffmpeg():
    if ffmpeg_installed():
        log.info("ffmpeg already installed, skipping")
        return False
    log.info("Installing FFmpeg")
    apt("apt install -y ffmpeg")
    return True

def ffmpeg_installed():
    if shutil.which("ffmpeg"):
        return (True)
    return (False)


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
    if width > 1200:
        width = 1200

    index_contents = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Raspberry Pi Camera</title>
    <style>
        html body .page {{ height: 100%; width: 100%; }}
        video {{ width: {width}px; }}
        .wrapper {{ width: {width}px; margin: auto; }}
    </style>
</head>
<body>
<div class="page">
    <div class="wrapper">
        <h1>Raspberry Pi Camera</h1>
        <video data-dashjs-player autoplay controls src="manifest.mpd" type="application/dash+xml"></video>
    </div>
</div>
<script src="http://cdn.dashjs.org/latest/dash.all.debug.js" ></script>
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
    cmd(f"/bin/bash {on_reboot_file}")


def prepare_ffmpeg_command(
    input_format, video_size, video_device, codec, ffmpeg_params, fmt, disable_hls=False, path=None, bitrate="dynamic"
):
    default_paths = {"dash": "/dev/shm/streaming/manifest.mpd", "rtsp": "rtsp://localhost:8554/streaming"}
    if not path:
        path = default_paths[fmt]

    if ffmpeg_params:
        ffmpeg_params = ffmpeg_params.strip("\"'")

    if codec != "copy":
        if "-b" not in ffmpeg_params:
            if bitrate == "dynamic":
                x, y = video_size.split("x")
                bitrate = (int(x) * int(y) * 2) // 1024
                ffmpeg_params += f" -b:v {bitrate}k"
            elif not bitrate.lower().endswith(("m", "k", "g")):
                bitrate += "k"
                ffmpeg_params += f" -b:v {bitrate}"
            else:
                ffmpeg_params += f" -b:v {bitrate}"
        if "-pix_fmt" not in ffmpeg_params:
            ffmpeg_params += " -pix_fmt yuv420p "

    if fmt == "dash":
        out = (
            "-f dash -remove_at_exit 1 -window_size 5 -use_timeline 1 -use_template 1 "
            f"{'' if disable_hls else '-hls_playlist 1 '}{path}"
        )
    elif fmt == "rtsp":
        out = f"-f rtsp {path}"
    else:
        raise Exception("Only support dash and rstp output currently")

    return (
        f"{shutil.which('ffmpeg')} -nostdin -hide_banner -loglevel error "
        f"-f v4l2 -input_format {input_format} -s {video_size} -i {video_device} "
        f"-c:v {codec} {ffmpeg_params if ffmpeg_params else ''} {out}"
    ).replace("  ", " ")


def install_ffmpeg_systemd_file(systemd_file, ffmpeg_command):
    systemd_contents = f"""# {systemd_file}
[Unit]
Description=Camera Streaming Service
After=network.target rc-local.service

[Service]
Restart=always
RestartSec=20s
ExecStart={ffmpeg_command}

[Install]
WantedBy=multi-user.target
"""

    if systemd_file.exists():
        if disable_overwrite:
            log.info(f"File {systemd_file} already exists. Not overwriting with: \n{systemd_file}")
            return
        log.warning(f"Systemd file exists at {systemd_file}, overwriting")
    log.info(f"Adding FFmpeg command to Systemd: {ffmpeg_command}")
    systemd_file.write_text(systemd_contents)
    systemd_file.chmod(0o755)
    log.info(f"Systemd file created at {systemd_file}.")
    cmd("systemctl daemon-reload")
    cmd(f"systemctl start {systemd_file.stem}")
    cmd(f"systemctl enable {systemd_file.stem}")


def install_rtsp_systemd(rtsp_systemd_file):
    contents = """# /etc/systemd/system/rtsp_server.service

[Unit]
Description=rtsp_server
After=network.target rc-local.service

[Service]
Restart=always
WorkingDirectory=/var/lib/streaming/
ExecStart=/var/lib/streaming/mediamtx

[Install]
WantedBy=multi-user.target
"""
    if rtsp_systemd_file.exists():
        if disable_overwrite:
            log.info(f"File {rtsp_systemd_file} already exists. Not overwriting with: \n{rtsp_systemd_file}")
            return
        log.warning(f"Systemd file exists at {rtsp_systemd_file}, overwriting")
    rtsp_systemd_file.write_text(contents)
    rtsp_systemd_file.chmod(0o755)
    log.info(f"rtsp server systemd file created at {rtsp_systemd_file}.")
    cmd("systemctl daemon-reload")
    cmd(f"systemctl start {rtsp_systemd_file.stem}")
    cmd(f"systemctl enable {rtsp_systemd_file.stem}")

def install_rtsp(rtsp_systemd_file):
    from urllib.request import urlopen
    import tarfile
    import platform

    sd = Path("/var/lib/streaming/")
    existing_version = None
    if sd.exists() and (sd / "mediamtx").exists():
        result = run(f"{sd / 'mediamtx'} --version", shell=True, stdout=PIPE, stderr=STDOUT)
        existing_version = result.stdout.decode("utf-8").strip()

    release_url = "https://api.github.com/repos/bluenviron/mediamtx/releases"

    log.info(f"Grabbing RTSP Server mediamtx information from github: {release_url}")

    rtsp_releases = json.loads(urlopen(release_url).read().decode("utf-8"))

    if existing_version:
        if rtsp_releases[0]["tag_name"] == existing_version:
            log.info("rtsp server is up to date")
            return
        else:
            log.info(f"Updating rtsp server from {existing_version} to {rtsp_releases[0]['tag_name']}")
            try:
                cmd(f"systemctl stop {rtsp_systemd_file.stem}")
            except Exception:
                pass

    log.info(f'Downloading RTSP Server mediamtx {rtsp_releases[0]["tag_name"]}')

    rtsp_assets = json.loads(urlopen(rtsp_releases[0]["assets_url"]).read().decode("utf-8"))

    # Detect the current OS
    system = platform.system().lower()
    if system == "darwin":
        os_type = "darwin"
    else:
        os_type = "linux"  # Default to Linux for Raspberry Pi and other Linux systems

    lscpu = lscpu_output()

    # Simplified architecture mappings based on the actual available files
    arch_mappings = {
        "armv7l": "armv7",  # Map to armv7 if it exists or we'll fall back to armv6
        "armv6l": "armv6",
        "aarch64": "arm64",
        "x86_64": "amd64",  # For Intel/AMD 64-bit processors
    }

    # If architecture isn't in our mapping, try the legacy mapping
    if lscpu["architecture"] not in arch_mappings:
        legacy_mappings = {
            "armv7l": "arm7",
            "armv6l": "arm6",
            "aarch64": "arm64v8",
            "x86_64": "amd64",
        }

        if lscpu["architecture"] not in legacy_mappings:
            log.error(f"Architecture {lscpu['architecture']} not found in mappings")
            available_assets = [asset["name"] for asset in rtsp_assets
                              if not asset["name"].endswith(".sha256sum")]
            log.error(f"Available assets: {available_assets}")
            raise Exception(f"mediamtx does not support architecture {lscpu['architecture']}")

        arch = legacy_mappings[lscpu["architecture"]]
    else:
        arch = arch_mappings[lscpu["architecture"]]

    log.info(f"Detected system: {os_type}, architecture: {arch}")
    sd.mkdir(exist_ok=True)

    # Get list of actual available architectures for fallback purposes
    available_assets = [asset["name"] for asset in rtsp_assets
                      if not asset["name"].endswith(".sha256sum")]

    # Construct expected filename pattern
    expected_pattern = f"{os_type}_{arch}"
    download_success = False

    # First attempt: find exact match
    for asset in rtsp_assets:
        if asset["name"].endswith(".sha256sum"):
            continue  # Skip checksum files

        asset_name = asset["name"].lower()
        if expected_pattern in asset_name:
            log.info(f"Found matching asset: {asset['name']}")
            with urlopen(asset["browser_download_url"]) as response, open(sd / asset["name"], "wb") as out_file:
                shutil.copyfileobj(response, out_file)
            with tarfile.open(sd / asset["name"]) as tf:
                tf.extractall(path=sd)
            download_success = True
            break

    # Second attempt: If armv7 wasn't found, try armv6 for armv7l architecture
    if not download_success and lscpu["architecture"] == "armv7l":
        fallback_pattern = f"{os_type}_armv6"
        log.info(f"Trying fallback from armv7 to armv6 for armv7l architecture")

        for asset in rtsp_assets:
            if asset["name"].endswith(".sha256sum"):
                continue

            asset_name = asset["name"].lower()
            if fallback_pattern in asset_name:
                log.info(f"Found fallback asset: {asset['name']}")
                with urlopen(asset["browser_download_url"]) as response, open(sd / asset["name"], "wb") as out_file:
                    shutil.copyfileobj(response, out_file)
                with tarfile.open(sd / asset["name"]) as tf:
                    tf.extractall(path=sd)
                download_success = True
                break

    # Third attempt: Try a more flexible matching approach
    if not download_success:
        log.warning(f"Could not find exact pattern {expected_pattern}, trying more flexible matching")
        for asset in rtsp_assets:
            if asset["name"].endswith(".sha256sum"):
                continue

            asset_name = asset["name"].lower()
            if os_type in asset_name and (arch in asset_name or
                                         (lscpu["architecture"] == "armv7l" and "armv6" in asset_name)):
                log.info(f"Found alternative match: {asset['name']}")
                with urlopen(asset["browser_download_url"]) as response, open(sd / asset["name"], "wb") as out_file:
                    shutil.copyfileobj(response, out_file)
                with tarfile.open(sd / asset["name"]) as tf:
                    tf.extractall(path=sd)
                download_success = True
                break

    if not download_success:
        filtered_assets = [a for a in available_assets if not a.endswith(".sha256sum")]
        log.error(f"Available assets: {filtered_assets}")
        raise Exception(f"Could not find download for rtsp server for {os_type}_{arch}")

def get_addresses():
    ips = run("hostname -I", shell=True, stdout=PIPE).stdout.decode("utf-8")
    hostname = run("hostname", shell=True, stdout=PIPE).stdout.decode("utf-8").strip()
    return ips.split() + [hostname]


def show_services():
    for host in get_addresses():
        log.info(f"Try viewing the stream at http://{host}/streaming")


def main():
    global disable_overwrite, rebuild_all

    args, ffmpeg_arguments_defaults_set = parse_arguments()

    if args.version:
        print(f"{__version__}")
        sys.exit(0)

    if os.geteuid() != 0:
        log.critical("This script requires root / sudo privileges")
        sys.exit(1)

    ffmpeg_installed=install_ffmpeg()

    if ffmpeg_installed:
        set_ffmpeg_argument_defaults(args, ffmpeg_arguments_defaults_set)

    if args.camera_info:
        all_cameras()
        sys.exit(0)

    output_path = None
    if args.rtsp and args.rtsp_url:
        output_path = args.rtsp_url

    ffmpeg_cmd = prepare_ffmpeg_command(
        input_format=args.input_format,
        video_size=args.video_size,
        video_device=args.device,
        codec=args.codec,
        ffmpeg_params=args.ffmpeg_params,
        fmt="rtsp" if args.rtsp else "dash",
        path=output_path,
        bitrate=args.bitrate,
    )

    if args.ffmpeg_command:
        print(ffmpeg_cmd)
        sys.exit()

    log.info(f"Starting streaming_setup {__version__}")
    arg_display = "\n\t".join([f"{k}: {v}" for k, v in vars(args).items()])
    log.debug(f"Using arguments:\n{arg_display}")
    index_file = Path(args.index_file)
    on_reboot_file = Path(args.on_reboot_file)
    systemd_file = Path(args.systemd_file)

    if not args.rtsp:
        index_file.parent.mkdir(parents=True, exist_ok=True)
        on_reboot_file.parent.mkdir(parents=True, exist_ok=True)

    if args.safe:
        disable_overwrite = True

    if args.rtsp and not args.rtsp_url:
        rtsp_systemd = Path("/etc/systemd/system/rtsp_server.service")
        install_rtsp(rtsp_systemd)
        install_rtsp_systemd(rtsp_systemd)
    elif not args.rtsp:
        install_nginx()
        update_rc_local_file(on_reboot_file=on_reboot_file)
        install_index_file(index_file=index_file, video_size=args.video_size)
        install_on_reboot_file(on_reboot_file=on_reboot_file, index_file=index_file)

    install_ffmpeg_systemd_file(systemd_file=systemd_file, ffmpeg_command=ffmpeg_cmd)

    log.info("\nInstall complete!")

    if args.rtsp and not args.rtsp_url:
        log.info("\nCreated two systemd services:\n\tstream_camera\n\trtsp_server")
        log.info("\nTo check their status, run:\n\tsystemctl status stream_camera\n\tsystemctl status rtsp_server\n")
        for host in get_addresses():
            log.info(f"View the stream at rtsp://{host}:8554/streaming")
    else:
        log.info("\nCreated systemd service:\n\tstream_camera")
        log.info("\nTo check the status, run:\n\tsystemctl status stream_camera\n")
        if not args.rtsp:
            show_services()

    if warn_no_camera:
        log.warning("\nCould not find a camera device, assuming user will connect pi camera.")
        log.warning(
            "If the camera later connected does not support h264, "
            f"you will have to manually modify the systemd file {systemd_file}."
        )


if __name__ == "__main__":
    main()
