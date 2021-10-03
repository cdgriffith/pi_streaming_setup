#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
This script is designed to help automate turing a raspberry pi with a
compatible video4linux2 camera into a MPEG-DASH / HLS streaming server.

The steps it will attempt to take:

* Install nginx
* Install FFmpeg OR (optional) Compile and Install FFmpeg with h264 hardware acceleration
* Update rc.local to run required setup script on reboot
* Create index.html file to view video stream at
* Create systemd service and enable it

If you will be compiling while running over SSH, please use in a background terminal like "tmux" or "screen".

If you are compilng FFmpeg, be aware, this will build a NON REDISTRIBUTABLE FFmpeg.
You will not be able to share the built binaries under any license.
"""

import logging
import os
import sys
import shutil
import pwd
import datetime
import json
from subprocess import run, CalledProcessError, PIPE, STDOUT, Popen
from pathlib import Path
from argparse import ArgumentParser

__author__ = "Chris Griffith"
__version__ = "1.6.2"

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
run_as = "root"
rebuild_all = False

# Different levels of FFmpeg configurations
# They are set to be in format ( configuration flag(s), apt library(s) )

# Minimal h264, x264, alsa sound and fonts
minimal_ffmpeg_config = [
    ("--enable-libx264", "libx264-dev"),
    ("--enable-indev=alsa --enable-outdev=alsa", "libasound2-dev"),
    ("--enable-mmal --enable-omx --enable-omx-rpi", "libomxil-bellagio-dev"),
    ("--enable-libfreetype", "libfreetype6-dev fonts-freefont-ttf"),
]

all_ffmpeg_config = minimal_ffmpeg_config + [
    ("--enable-libx265", "libx265-dev"),
    ("--enable-libvpx", "libvpx-dev"),
    ("--enable-libmp3lame", "libmp3lame-dev"),
    ("--enable-libvorbis", "libvorbis-dev"),
    ("--enable-libopus", "libopus-dev"),
    ("--enable-libtheora", "libtheora-dev"),
    ("--enable-libopenjpeg", "libopenjpeg-dev libopenjp2-7-dev"),  # aarch64 64 issues
    ("--enable-librtmp", "librtmp-dev"),
    ("--enable-libass", "libass-dev"),
    ("--enable-swresample", "libswresample-dev"),
    ("--enable-fontconfig", "libfontconfig1-dev"),
    ("--enable-chromaprint", "libchromaprint-dev"),
    ("--enable-frei0r", "frei0r-plugins-dev"),
    ("--enable-libsoxr", "libsoxr-dev"),
    ("--enable-libwebp", "libwebp-dev"),
    ("--enable-libbluray", "libbluray-dev"),
    ("--enable-librubberband", "librubberband-dev"),
    ("--enable-libspeex", "libspeex-dev"),
    ("--enable-libvidstab", "libvidstab-dev"),
    ("--enable-libxvid", "libxvidcore-dev"),
    ("--enable-libxml2", "libxml2-dev"),
    ("--enable-libfribidi", "libfribidi-dev"),
    ("--enable-libgme", "libgme-dev"),
    ("--enable-openssl", "libssl-dev"),
    ("--enable-gmp", "libgmp-dev"),
    ("--enable-libbs2b", "libbs2b-dev"),
    ("--enable-libcaca", "libcaca-dev"),
    ("--enable-libcdio", "libcdio-dev libcdio-paranoia-dev"),
    ("--enable-libdc1394", "libdc1394-22-dev"),
    ("--enable-libflite", "flite1-dev"),
    ("--enable-libfontconfig", "libfontconfig1-dev"),
    ("--enable-libgsm", "libgsm1-dev"),
    ("--enable-libjack", "libjack-dev libjack0"),
    ("--enable-libmodplug", "libmodplug-dev"),
    ("--enable-libopenmpt", "libopenmpt-dev"),
    ("--enable-libpulse", "libpulse-dev"),
    ("--enable-librsvg", "librsvg2-dev"),
    ("--enable-libshine", "libshine-dev"),
    ("--enable-libsnappy", "libsnappy-dev"),
    ("--enable-libssh", "libssh-dev"),
    ("--enable-libtesseract", "libtesseract-dev"),
    ("--enable-libtwolame", "libtwolame-dev"),
    ("--enable-libxcb", "libxcb1-dev"),
    ("--enable-libxcb-shm", "libxcb-shm0-dev"),
    ("--enable-libxcb-xfixes", "libxcb-xfixes0-dev"),
    ("--enable-libxcb-shape", "libxcb-shape0-dev"),
    ("--enable-libzmq", "libzmq3-dev"),
    ("--enable-libzvbi", "libzvbi-dev"),
    ("--enable-libdrm", "libdrm-dev"),
    ("--enable-openal", "libopenal-dev"),
    ("--enable-opengl", "libopengl-dev"),  # aarch64 issues
    ("--enable-ladspa", "libags-audio-dev libladspa-ocaml-dev"),
    ("--enable-sdl2", "libsdl2-dev"),
    ("--enable-libcodec2", "libcodec2-dev"),
    ("--enable-lv2", "lv2-dev liblilv-dev"),
    ("--enable-libaom", "libaom-dev"),
    ("--enable-libopencore-amrwb", "libopencore-amrwb-dev"),
    ("--enable-libopencore-amrnb", "libopencore-amrnb-dev"),
    ("--enable-libvo-amrwbenc", "libvo-amrwbenc-dev"),
    # ("--enable-libwavpack", "libwavpack-dev"), # Option removed as of 10/22/20
    # ('--enable-libmysofa', 'libmysofa-dev'), # error: 'mysofa_neighborhood_init_withstepdefine' undeclared
    # ('--enable-libsmbclient', 'libsmbclient-dev'),  # not found, even with --extra-cflags="-I/usr/include/samba-4.0"
    # ('--enable-libiec61883', 'libiec61883-dev libiec61883-0'), # cannot find -lavc1394, cannot find -lrom1394
]


def parse_arguments():
    device, fmt, resolution = find_best_device()
    codec = "copy" if fmt == "h264" else "h264_omx"

    parser = ArgumentParser(prog="streaming_setup", description=f"streaming_setup version {__version__}")
    parser.add_argument("-v", "--version", action="store_true")
    parser.add_argument("--ffmpeg-command", action="store_true", help="print the automated FFmpeg command and exit")
    parser.add_argument("-d", "-i", "--device", default=str(device), help=f"Camera. Selected: {device}")
    parser.add_argument(
        "-s", "--video-size", default=resolution, help=f"The video resolution from the camera (using {resolution})"
    )
    parser.add_argument("-r", "--rtsp", action="store_true", help="Use RTSP instead of DASH / HLS")
    parser.add_argument("--rtsp-url", default="",
                        help="Provide a remote RTSP url to connect to and don't set up a local server")
    parser.add_argument("-f", "--input-format", default=fmt, help=f"The format the camera supports (using {fmt})")
    parser.add_argument("-b", "--bitrate", default="dynamic", help=f"Streaming bitrate, is auto calculated by default."
                                                                   f" (Will be ignored if the codec is 'copy')")
    parser.add_argument("-c", "--codec", default=codec, help=f"Conversion codec (using '{codec}')")
    parser.add_argument(
        "--ffmpeg-params", default="",
        help="specify additional FFmpeg params, MUST be doubled quoted! helpful "
             "if not copying codec e.g.: '\"-b:v 4M -maxrate 4M -buffsize 8M\"' ",
    )
    parser.add_argument("--index-file", default="/var/lib/streaming/index.html")
    parser.add_argument("--on-reboot-file", default="/var/lib/streaming/setup_streaming.sh")
    parser.add_argument("--systemd-file", default="/etc/systemd/system/stream_camera.service")
    parser.add_argument("--compile-ffmpeg", action="store_true")
    parser.add_argument("--compile-only", action="store_true")
    parser.add_argument(
        "--camera-info", action="store_true", help="Show all detected cameras [/dev/video(0-9)] and exit"
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Minimal FFmpeg compile including h264, x264, alsa sound and fonts",
    )
    parser.add_argument(
        "--run-as", default="root", help="compile programs as provided user (suggested 'pi', defaults to 'root')"
    )
    parser.add_argument("--disable-fdk-aac", action="store_true", help="Normally installed on full install")
    parser.add_argument("--disable_avisynth", action="store_true", help="Normally installed on full install")
    parser.add_argument("--disable-dav1d", action="store_true", help="Normally installed on full install")
    parser.add_argument("--disable-zimg", action="store_true", help="Normally installed on full install")
    parser.add_argument("--disable-kvazaar", action="store_true", help="Normally installed on full install")
    parser.add_argument("--disable-libxavs", action="store_true", help="Normally installed on full install")
    parser.add_argument("--disable-libsrt", action="store_true", help="Normally installed on full install")
    parser.add_argument("--rebuild-all", action="store_true", help="Recompile all libraries")
    parser.add_argument("--safe", action="store_true", help="disable overwrite of existing or old scripts")
    return parser.parse_args()


def cmd(command, cwd=here, env=None, demote=True, **kwargs):
    environ = os.environ.copy()
    if env:
        environ.update(env)

    preexec_fn = None
    if demote:
        pw_record = pwd.getpwnam(run_as)
        environ["HOME"] = pw_record.pw_dir
        environ["LOGNAME"] = pw_record.pw_name
        environ["PWD"] = cwd
        environ["USER"] = pw_record.pw_name

        def preexec_fn_demote_wrapper(uid, gid):
            def demote_to_user():
                os.setgid(uid)
                os.setuid(gid)

            return demote_to_user

        preexec_fn = preexec_fn_demote_wrapper(pw_record.pw_uid, pw_record.pw_gid)

    log.debug(f'Executing from "{cwd}" as user "{"root" if not demote else run_as }" command: {command} ')
    process = Popen(
        command, shell=True, cwd=cwd, stdout=PIPE, stderr=STDOUT, env=environ, preexec_fn=preexec_fn, **kwargs
    )
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
        return cmd(command, cwd, demote=False)
    except CalledProcessError:
        cmd("apt update --fix-missing", demote=False)
        return cmd(command, cwd, demote=False)


def lscpu_output():
    results = json.loads(run("lscpu -J", shell=True, stdout=PIPE).stdout.decode("utf-8").lower())
    return {x["field"].replace(':',''): x["data"] for x in results["lscpu"]}


def raspberry_proc_info(cores_only=False):
    results = lscpu_output()
    if cores_only:
        return int(results.get('cpu(s)', 1))
    log.info(f"Model Info: {Path('/proc/device-tree/model').read_text()}")
    if 'architecture' not in results:
        log.warning(f"Could not grab architecture information from lscpu, defaulting to armhf: {results}")
        return "--arch=armhf "
    if "armv7" in results['architecture']:
        if "cortex-a72" in results['model name']:
            # Raspberry Pi 4 Model B
            log.info("Optimizing for cortex-a72 processor")
            return (
                "--arch=armv7 --cpu=cortex-a72 --enable-neon "
                "--extra-cflags='-mtune=cortex-a72 -mfpu=neon-vfpv4 -mfloat-abi=hard'"
            )
        if "cortex-a53" in results['model name']:
            # Raspberry Pi 3 Model B
            log.info("Optimizing for cortex-a53 processor")
            return (
                "--arch=armv7 --cpu=cortex-a53 --enable-neon "
                "--extra-cflags='-mtune=cortex-a53 -mfpu=neon-vfpv4 -mfloat-abi=hard'"
            )
        log.info("Using architecture 'armv7'")
        return "--arch=armv7 --enable-neon "
    if "armv6" in results['architecture']:
        # Raspberry Pi Zero
        log.info("Using architecture 'armv6'")
        return "--arch=armv6"
    if "aarch64" in results['architecture']:
        # Using new raspberry pi 64 bit OS
        log.info("Using architecture 'aarch64'")
        raise Exception("This may break with the current Raspberry Pi 64 bit build as of 07/2020. "
                        "Only remove this line of code and uncomment next one "
                        "if you are prepared to reinstall the OS if it doesn't work. (Please report if it works)")
        # return "--arch=aarch64"
    log.info("Defaulting to architecture 'armhf'")
    return "--arch=armhf"


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
    if shutil.which("ffmpeg"):
        log.info("ffmpeg already installed, skipping")
        return
    log.info("Installing FFmpeg")
    apt("apt install -y ffmpeg")


def compile_ffmpeg(extra_libs, minimal_install=False):
    ffmpeg_configures, apt_installs = [], []

    for f, a in (all_ffmpeg_config if not minimal_install else minimal_ffmpeg_config):
        ffmpeg_configures.append(f)
        apt_installs.append(a)

    ffmpeg_libs = "{}".format(" ".join(ffmpeg_configures))
    processor_info = raspberry_proc_info()  # Needs to be here to proper error before the apt install

    log.info("Installing FFmpeg requirements")
    apt("apt install -y git checkinstall build-essential {}".format(" ".join(apt_installs)))

    ffmpeg_dir = here / "FFmpeg"
    if not ffmpeg_dir.exists():
        log.info("Grabbing FFmpeg")
        cmd("git clone https://github.com/FFmpeg/FFmpeg.git FFmpeg --depth 1", cwd=here)
    else:
        log.info("FFmpeg exists: updating FFmpeg via git pull")
        cmd("git pull", cwd=ffmpeg_dir)

    log.info("Configuring FFmpeg")
    cmd(
        f"./configure {processor_info} --target-os=linux "
        '--extra-libs="-lpthread -lm" --extra-ldflags="-latomic" '
        "--enable-static --disable-shared --disable-debug --enable-gpl --enable-version3 --enable-nonfree  "
        f"{ffmpeg_libs} {extra_libs}",
        cwd=ffmpeg_dir,
    )

    log.info("Building FFmpeg (This will take a while)")
    cmd(f"make {'-j4' if raspberry_proc_info(cores_only=True) >= 4 else ''}", cwd=ffmpeg_dir)
    install_compiled_ffmpeg()


def ensure_library_dir():
    lib_path = Path(here, "ffmpeg-libraries")
    return user_dir(lib_path)


def user_dir(new_path):
    new_path.mkdir(exist_ok=True)
    pw_record = pwd.getpwnam(run_as)
    os.chown(new_path, pw_record.pw_uid, pw_record.pw_gid)
    return new_path


def install_fdk_aac():
    if not rebuild_all and Path("/usr/local/lib/libfdk-aac.la").exists():
        log.info("libfdk-aac already built")
        return "--enable-libfdk-aac"

    log.info("Building libfdk-aac")
    lib_dir = ensure_library_dir()
    sub_dir = lib_dir / "fdk_aac"
    apt("apt install -y automake libtool")
    if sub_dir.exists():
        cmd("git pull", cwd=sub_dir)
    else:
        cmd(f"git clone --depth 1 https://github.com/mstorsjo/fdk-aac.git fdk_aac", cwd=lib_dir)
    cmd("autoreconf -fiv", cwd=sub_dir)
    cmd("./configure", cwd=sub_dir)
    cmd(f"make {'-j4' if raspberry_proc_info(cores_only=True) >= 4 else ''}", cwd=sub_dir)
    cmd("make install", cwd=sub_dir, demote=False)
    return "--enable-libfdk-aac"


def install_avisynth():
    if not rebuild_all and Path("/usr/local/include/avisynth/avisynth_c.h").exists():
        log.info("AviSynth headers already built")
        return "--enable-avisynth"

    log.info("Building AviSynth headers")
    apt("apt install -y cmake")
    lib_dir = ensure_library_dir()
    sub_dir = lib_dir / "AviSynthPlus"
    if sub_dir.exists():
        cmd("git pull", cwd=sub_dir)
    else:
        cmd(f"git clone --depth 1 https://github.com/AviSynth/AviSynthPlus.git AviSynthPlus", cwd=lib_dir)
    build_dir = user_dir(sub_dir / "avisynth-build")
    cmd("cmake ../ -DHEADERS_ONLY:bool=on", cwd=build_dir)
    cmd("make install", cwd=build_dir, demote=False)
    return "--enable-avisynth"


def install_libxavs():
    if not rebuild_all and shutil.which("xavs"):
        log.info("xavs already built")
        return "--enable-libxavs"

    log.info("Building xavs headers")
    apt("apt install -y subversion")
    lib_dir = ensure_library_dir()
    sub_dir = lib_dir / "xavs"
    if sub_dir.exists():
        cmd("git pull", cwd=sub_dir)
    else:
        cmd(f"svn co https://svn.code.sf.net/p/xavs/code/trunk xavs", cwd=lib_dir)
    cmd("./configure --enable-shared", cwd=sub_dir)
    cmd("make", cwd=sub_dir)
    cmd("make install", cwd=sub_dir, demote=False)
    return "--enable-libxavs"


def install_srt():
    if not rebuild_all and Path("/usr/local/include/srt").exists():
        log.info("srt already built")
        return "--enable-libsrt"

    log.info("Building srt headers")
    apt("apt install -y tclsh pkg-config cmake libssl-dev build-essential")
    lib_dir = ensure_library_dir()
    sub_dir = lib_dir / "srt"
    if sub_dir.exists():
        cmd("git pull", cwd=sub_dir)
    else:
        cmd(f"git clone --depth 1 https://github.com/Haivision/srt.git srt", cwd=lib_dir)
    cmd("./configure", cwd=sub_dir)
    cmd("make", cwd=sub_dir)
    cmd("make install", cwd=sub_dir, demote=False)
    return "--enable-libsrt"


def install_dav1d():
    if not rebuild_all and shutil.which("dav1d"):
        log.info("dav1d already built")
        return "--enable-libdav1d"

    log.info("Building dav1d")
    lib_dir = ensure_library_dir()
    sub_dir = lib_dir / "dav1d"

    apt("apt install -y meson ninja-build")
    if sub_dir.exists():
        cmd("git pull", cwd=sub_dir)
    else:
        cmd(f"git clone --depth 1 https://code.videolan.org/videolan/dav1d.git dav1d", cwd=lib_dir)
    build_dir = user_dir(sub_dir / "build")

    cmd("meson ..", cwd=build_dir)
    cmd("ninja", cwd=build_dir)
    cmd("ninja install", cwd=build_dir, demote=False)
    return "--enable-libdav1d"


def install_zimg():
    if not rebuild_all and Path("/usr/local/lib/libzimg.la").exists():
        log.info("libzimg already built")
        return "--enable-libzimg"

    log.info("Building libzimg")
    lib_dir = ensure_library_dir()
    sub_dir = lib_dir / "zimg"
    if sub_dir.exists():
        cmd("git pull", cwd=sub_dir)
    else:
        cmd(f"git clone https://github.com/sekrit-twc/zimg.git zimg", cwd=lib_dir)
    cmd("sh autogen.sh", cwd=sub_dir)
    cmd("./configure", cwd=sub_dir)
    cmd("make", cwd=sub_dir)
    cmd("make install", cwd=sub_dir, demote=False)
    return "--enable-libzimg"


def install_kvazaar():
    if not rebuild_all and shutil.which("kvazaar"):
        log.info("libkvazaar already built")
        return "--enable-libkvazaar"

    log.info("Building libkvazaar")
    lib_dir = ensure_library_dir()
    sub_dir = lib_dir / "kvazaar"
    if sub_dir.exists():
        cmd("git pull", cwd=sub_dir)
    else:
        cmd(f"git clone --depth 1 https://github.com/ultravideo/kvazaar.git kvazaar", cwd=lib_dir)
    cmd("sh autogen.sh", cwd=sub_dir)
    cmd("./configure", cwd=sub_dir)
    cmd(f"make {'-j4' if raspberry_proc_info(cores_only=True) >= 4 else ''}", cwd=sub_dir)
    cmd("make install", cwd=sub_dir, demote=False)
    return "--enable-libkvazaar"


# vmaf giving error: test/meson.build:7:0: ERROR:  Include directory to be added is not an include directory object.
# def install_vmaf():
#     # figure out how to detect vmaf installed
#     lib_dir = ensure_library_dir()
#
#     log.info("Building libvmaf")
#     apt("apt install -y meson ninja-build doxygen")
#     if (lib_dir / "vmaf").exists():
#         cmd("git pull", cwd=(lib_dir / "vmaf"))
#     else:
#         cmd(f"git clone --depth 1 https://github.com/ultravideo/kvazaar.git kvazaar", cwd=lib_dir)
#     sub_dir = user_dir(lib_dir / "vmaf" / "libvmaf")
#     cmd("meson build --buildtype release", cwd=sub_dir)
#     cmd("ninja -vC build", cwd=sub_dir)
#     cmd("ninja -vC build install", cwd=sub_dir)
#     return "--enable-libvmaf"


def install_compiled_ffmpeg():
    log.info("Installing FFmpeg")
    apt(f"apt remove ffmpeg -y {'' if disable_overwrite else '--allow-change-held-packages'} ")
    cmd("checkinstall --pkgname=ffmpeg -y", cwd=here / "FFmpeg", demote=False)
    cmd("apt-mark hold ffmpeg", demote=False)
    cmd('echo "ffmpeg hold" | sudo dpkg --set-selections', demote=False)


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
    cmd(f"/bin/bash {on_reboot_file}", demote=False)


def prepare_ffmpeg_command(input_format,
                           video_size,
                           video_device,
                           codec,
                           ffmpeg_params,
                           fmt,
                           disable_hls=False,
                           path=None,
                           bitrate="dynamic"):
    default_paths = {'dash': "/dev/shm/streaming/manifest.mpd",
                     "rtsp": "rtsp://localhost:8554/streaming"}
    if not path:
        path = default_paths[fmt]

    if ffmpeg_params:
        ffmpeg_params = ffmpeg_params.strip("\"'")

    if codec != "copy":
        if "-b" not in ffmpeg_params and bitrate == "dynamic":
            x, y = video_size.split("x")
            bitrate = (int(x) * int(y) * 2) // 1024
            ffmpeg_params += f" -b:v {bitrate}k"
        else:
            if not bitrate.lower().endswith(("m", "k", "g")):
                bitrate += "k"
            ffmpeg_params += f" -b:v {bitrate}"

    if fmt == "dash":
        out = ("-f dash -remove_at_exit 1 -window_size 5 -use_timeline 1 -use_template 1 "
              f"{'' if disable_hls else '-hls_playlist 1 '}{path}")
    elif fmt == "rtsp":
        out = f"-f rtsp {path}"
    else:
        raise Exception("Only support dash and rstp output currently")

    return (
        "ffmpeg -nostdin -hide_banner -loglevel error "
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
    cmd("systemctl daemon-reload", demote=False)
    cmd(f"systemctl start {systemd_file.stem}", demote=False)
    cmd(f"systemctl enable {systemd_file.stem}", demote=False)


def install_rtsp_systemd(rtsp_systemd_file):
    contents = """# /etc/systemd/system/rtsp_server.service

[Unit]
Description=rtsp_server
After=network.target rc-local.service

[Service]
Restart=always
WorkingDirectory=/var/lib/streaming/
ExecStart=/var/lib/streaming/rtsp-simple-server

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
    cmd("systemctl daemon-reload", demote=False)
    cmd(f"systemctl start {rtsp_systemd_file.stem}", demote=False)
    cmd(f"systemctl enable {rtsp_systemd_file.stem}", demote=False)


def install_rtsp():
    from urllib.request import urlopen
    import shutil
    import tarfile
    rtsp_releases = json.loads(urlopen(f"https://api.github.com/repos/aler9/rtsp-simple-server/releases").read().decode('utf-8'))
    rtsp_assets = json.loads(urlopen(rtsp_releases[0]["assets_url"]).read().decode('utf-8'))
    lscpu = lscpu_output()
    mappings = {
        "armv7l": "armv7",
        "armv6l": "armv6",
        "aarch64": "armv64"
    }
    if lscpu["architecture"] not in mappings:
        # Old mapping style for safety
        mappings = {
            "armv7l": "arm7",
            "armv6l": "arm6",
            "aarch64": "arm64"
        }
        if lscpu["architecture"] not in mappings:
            raise Exception(f"Don't know the arch {lscpu['architecture']}")

    arch = mappings[lscpu["architecture"]]

    sd = Path("/var/lib/streaming/")
    sd.mkdir(exist_ok=True)
        
    for asset in rtsp_assets:
        if arch in asset["name"]:
            with urlopen(asset["browser_download_url"]) as response, open(sd / asset["name"], 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
            with tarfile.open(sd / asset["name"]) as tf:
                tf.extractall(path=sd)
            break
    else:
        raise Exception("Could not find download for rtsp server")


def show_services():
    ips = run("hostname -I", shell=True, stdout=PIPE).stdout.decode("utf-8")
    hostname = run("hostname", shell=True, stdout=PIPE).stdout.decode("utf-8").strip()
    for host in ips.split() + [hostname]:
        log.info(f"Try viewing the stream at http://{host}/streaming")


def main():
    global disable_overwrite, run_as, rebuild_all
    args = parse_arguments()
    if args.version:
        print(f"{__version__}")
        sys.exit(0)

    if os.geteuid() != 0:
        log.critical("This script requires root / sudo privileges")
        sys.exit(1)

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
        bitrate=args.bitrate
    )

    if args.ffmpeg_command:
        print(ffmpeg_cmd)
        sys.exit()

    if args.run_as != "root":
        run_as = args.run_as
        try:
            pwd.getpwnam(run_as)
        except KeyError:
            log.critical(f"Cannot run as {run_as} as that user does not exist!")
            sys.exit(1)

    log.info(f"Starting streaming_setup {__version__}")
    log.debug(f"Using arguments: {vars(args)}")
    index_file = Path(args.index_file)
    on_reboot_file = Path(args.on_reboot_file)
    systemd_file = Path(args.systemd_file)

    if not args.rtsp:
        index_file.parent.mkdir(parents=True, exist_ok=True)
        on_reboot_file.parent.mkdir(parents=True, exist_ok=True)

    if args.safe:
        disable_overwrite = True

    if args.compile_ffmpeg or args.compile_only:
        if args.rebuild_all:
            rebuild_all = True

        log.info(f"Performing \"{'minimal' if args.minimal else 'full'}\" FFmpeg compile")
        apt("apt install -y git build-essential")
        extra_libs = []
        if not args.minimal:
            if not args.disable_fdk_aac:
                extra_libs.append(install_fdk_aac())
            if not args.disable_avisynth:
                extra_libs.append(install_avisynth())
            if not args.disable_zimg:
                extra_libs.append(install_zimg())
            if not args.disable_dav1d:
                extra_libs.append(install_dav1d())
            if not args.disable_kvazaar:
                extra_libs.append(install_kvazaar())
            if not args.disable_libxavs:
                extra_libs.append(install_libxavs())
            if not args.disable_libsrt:
                extra_libs.append(install_srt())
            cmd("ldconfig", demote=False)
        compile_ffmpeg(
            extra_libs=" ".join(extra_libs), minimal_install=args.minimal,
        )
    else:
        install_ffmpeg()

    if args.compile_only:
        log.info("Compile complete!")
        return

    if args.rtsp and not args.rtsp_url:
        install_rtsp()
        install_rtsp_systemd(Path("/etc/systemd/system/rtsp_server.service"))
    elif not args.rtsp:
        install_nginx()
        update_rc_local_file(on_reboot_file=on_reboot_file)
        install_index_file(index_file=index_file, video_size=args.video_size)
        install_on_reboot_file(on_reboot_file=on_reboot_file, index_file=index_file)
        show_services()

    install_ffmpeg_systemd_file(systemd_file=systemd_file, ffmpeg_command=ffmpeg_cmd)

    log.info("Install complete!")


if __name__ == "__main__":
    main()
