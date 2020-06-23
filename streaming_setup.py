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

This will build a NON REDISTRIBUTABLE FFmpeg. Please be aware you will not be able to share the built binaries
under any license.


"""
import logging
import os
import sys
import shutil
import datetime
from subprocess import run, CalledProcessError, PIPE, STDOUT, Popen
from pathlib import Path
from argparse import ArgumentParser

__author__ = "Chris Griffith"
__version__ = "1.2.0"

log = logging.getLogger("streaming_setup")
command_log = logging.getLogger("streaming_setup.command")
CMD_LVL = 15
logging.addLevelName(CMD_LVL, "CMD")

logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s - %(name)-12s  %(levelname)-8s %(message)s",
                    filename=f"streaming_setup_{datetime.datetime.now().strftime('%Y%M%d_%H%M%S')}.log")

sh = logging.StreamHandler(sys.stdout)
log.setLevel(logging.DEBUG)
command_log.setLevel(logging.DEBUG)
log.addHandler(sh)

here = Path(__file__).parent
disable_overwrite = False

# Different levels of FFmpeg configurations
# They are set to be in format ( configuration flag(s), apt library(s) )

# Minimal h264, x264, alsa sound and fonts
minimal_ffmpeg_config = [
    ("--enable-libx264", "libx264-dev"),
    ("--enable-indev=alsa --enable-outdev=alsa", "libasound2-dev"),
    ("--enable-mmal --enable-omx --enable-omx-rpi", "libomxil-bellagio-dev"),
    ("--enable-libfreetype", "libfreetype6-dev fonts-freefont-ttf"),
]

# Recommenced, also installs fdk-aac  (takes about 15 minutes on a Pi 4)
standard_ffmpeg_config = minimal_ffmpeg_config + [
    ("--enable-libx265", "libx265-dev"),
    ("--enable-libvpx", "libvpx-dev"),
    ("--enable-libmp3lame", "libmp3lame-dev"),
    ("--enable-libvorbis", "libvorbis-dev"),
    ("--enable-libopus", "libopus-dev"),
    ("--enable-libtheora", "libtheora-dev"),
    ("--enable-libopenjpeg", "libopenjpeg-dev libopenjp2-7-dev"),
    ("--enable-librtmp", "librtmp-dev"),
]

# Everything and the kitchen sink
all_ffmpeg_config = standard_ffmpeg_config + [
    ("--enable-libass", "libass-dev"),
    ("--enable-avresample", "libavresample-dev"),
    ("--enable-fontconfig", "libfontconfig1-dev"),
    ("--enable-chromaprint", "libchromaprint-dev"),
    ("--enable-frei0r", "frei0r-plugins-dev"),
    ("--enable-libsoxr", "libsoxr-dev"),
    ("--enable-libwebp", "libwebp-dev"),
    ("--enable-libbluray", "libbluray-dev"),
    ("--enable-libopencore-amrwb", "libopencore-amrwb-dev"),
    ("--enable-libopencore-amrnb", "libopencore-amrnb-dev"),
    ("--enable-libvo-amrwbenc", "libvo-amrwbenc-dev"),
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
    ("--enable-libwavpack", "libwavpack-dev"),
    ("--enable-libxcb", "libxcb1-dev"),
    ("--enable-libxcb-shm", "libxcb-shm0-dev"),
    ("--enable-libxcb-xfixes", "libxcb-xfixes0-dev"),
    ("--enable-libxcb-shape", "libxcb-shape0-dev"),
    ("--enable-libzmq", "libzmq3-dev"),
    ("--enable-libzvbi", "libzvbi-dev"),
    ("--enable-libdrm", "libdrm-dev"),
    ("--enable-openal", "libopenal-dev"),
    ("--enable-opengl", "libopengl-dev"),
    ('--enable-ladspa', 'libags-audio-dev libladspa-ocaml-dev'),
    ('--enable-sdl2', 'libsdl2-dev'),
    ('--enable-libcodec2', 'libcodec2-dev'),
    ('--enable-lv2', 'lv2-dev liblilv-dev'),
    # ('--enable-gray', ''),
    # ('--enable-rpi', ''),
    # ('--enable-libsrt', ''),
    # ('--enable-sdl2', ''),
    # ('--enable-libaom', ''),
    # ('--enable-libmysofa', 'libmysofa-dev'), # ERROR: libmysofa not found
    # ('--enable-libsmbclient', 'libsmbclient-dev'), # ERROR: libsmbclient not found
    # ('--enable-libopencv', 'libopencv-dev libopencv-apps-dev'),  # ERROR: libopencv not found
    # ('--enable-libiec61883', 'libiec61883-dev libiec61883-0'),  # ERROR: libiec61883 not found
    # ('--enable-libcelt', 'libcelt-dev'), # ERROR: libcelt must be installed and version must be >= 0.11.0.
]


def parse_arguments():
    device, fmt, resolution = find_best_device()

    parser = ArgumentParser(prog="streaming_setup", description=f"streaming_setup version {__version__}")
    parser.add_argument("-v", "--version", action="store_true")
    parser.add_argument(
        "-d", "-i", "--device", default=str(device), help=f"Camera. Selected: {device}"
    )
    parser.add_argument(
        "-s", "--video-size", default=resolution, help=f"The video resolution from the camera (using {resolution})"
    )
    parser.add_argument(
        "-f", "--input-format", default=fmt, help=f"The format the camera supports (using {fmt})"
    )
    parser.add_argument(
        "-c", "--codec",
        default="copy",
        help="Conversion codec (default is 'copy')"
    )
    parser.add_argument(
        "--ffmpeg-params",
        help="specify additional ffmpeg params, helpful if not copying codec e.g.: '-b:v 4M -maxrate 4M -buffsize 8M' "
    )
    parser.add_argument("--index-file", default="/var/www/html/index.html")
    parser.add_argument("--on-reboot-file", default="/opt/setup_streaming.sh")
    parser.add_argument("--systemd-file", default="/etc/systemd/system/encode_webcam.service")
    parser.add_argument("--compile-ffmpeg", action="store_true")
    parser.add_argument(
        "--install-type",
        default="standard",
        help="(min,standard,all) When compiling, select which ffmpeg libraries to use. Defaults to 'standard'",
    )
    parser.add_argument("--disable-fdk-aac", action="store_true", help="Normally installed on 'standard' install")
    parser.add_argument("--disable_avisynth", action="store_true", help="Normally installed on 'standard' install")
    parser.add_argument("--disable-dav1d", action="store_true", help="Normally installed on 'all' install")
    parser.add_argument("--disable-zimg", action="store_true", help="Normally installed on 'all' install")
    parser.add_argument("--disable_kvazaar", action="store_true", help="Normally installed on 'all' install")
    parser.add_argument("--disable_libxavs", action="store_true", help="Normally installed on 'all' install")
    # parser.add_argument("--disable_vmaf", action="store_true")
    parser.add_argument("--safe", action="store_true", help="disable overwrite of existing scripts")
    return parser.parse_args()


def cmd(command, cwd=here, env=None, **kwargs):
    log.debug(f"Executing command: {command} in working directory {cwd}")
    if env:
        env.update(os.environ.copy())
    process = Popen(command, shell=True, cwd=cwd, stdout=PIPE, stderr=STDOUT, env=env, **kwargs)
    while True:
        output = process.stdout.readline().decode("utf-8").strip()
        if output == '' and process.poll() is not None:
            break
        command_log.log(CMD_LVL, output)
    return_code = process.poll()
    if return_code > 0:
        raise CalledProcessError(returncode=return_code, cmd=command)
    result = run(command, shell=True, cwd=cwd)
    result.check_returncode()


def apt(command, cwd=here):
    try:
        return cmd(command, cwd)
    except CalledProcessError:
        cmd("apt update --fix-missing")
        return cmd(command, cwd)


def raspberry_proc_info(cores_only=False):
    results = run("lscpu", stdout=PIPE).stdout.decode("utf-8").lower()
    if cores_only:
        for line in results.splitlines():
            if line.startswith("cpu(s):"):
                return int(line.split()[1].strip())
        else:
            return 1
    log.info(f"Model Info: {Path('/proc/device-tree/model').read_text()}")
    if "armv7" in results:
        if "cortex-a72" in results:
            # Raspberry Pi 4 Model B
            log.info("Optimizing for cortex-a72 processor")
            return (
                "--arch=armv7 --cpu=cortex-a72 --enable-neon "
                "--extra-cflags='-mtune=cortex-a72 -mfpu=neon-vfpv4 -mfloat-abi=hard'"
            )
        if "cortex-a53" in results:
            # Raspberry Pi 3 Model B
            log.info("Optimizing for cortex-a53 processor")
            return (
                "--arch=armv7 --cpu=cortex-a53 --enable-neon "
                "--extra-cflags='-mtune=cortex-a53 -mfpu=neon-vfpv4 -mfloat-abi=hard'"
            )
        log.info("Using architecture 'armv7'")
        return "--arch=armv7"
    if "armv6" in results:
        # Raspberry Pi Zero
        log.info("Using architecture 'armv6'")
        return "--arch=armv6"
    log.info("Defaulting to architecture 'armel'")
    return "--arch=armel"

def camera_info(device, hide_error=False):
    # ffmpeg -hide_banner -f video4linux2 -list_formats all -i /dev/video0
    # [video4linux2,v4l2 @ 0xf0cf70] Raw       :     yuyv422 :           YUYV 4:2:2 : {32-2592, 2}x{32-1944, 2}
    # [video4linux2,v4l2 @ 0xf0cf70] Compressed:       mjpeg :            JFIF JPEG : {32-2592, 2}x{32-1944, 2}
    # [video4linux2,v4l2 @ 0xf0cf70] Compressed:        h264 :                H.264 : {32-2592, 2}x{32-1944, 2}
    # [video4linux2,v4l2 @ 0xf0cf70] Compressed:       mjpeg :          Motion-JPEG : {32-2592, 2}x{32-1944, 2}
    data = run(f"ffmpeg -hide_banner -f video4linux2 -list_formats all -i {device}", shell=True, stdout=PIPE, stderr=PIPE)
    stdout, stderr = data.stdout.decode('utf-8'), data.stderr.decode('utf-8')
    if "Not a video capture device" in stdout or "Not a video capture device" in stderr:
        if not hide_error:
            log.error(f"{device} is not a video capture device ")
        return

    def get_best_resolution(res):
        if "{" in res:
            try:
                w, h = res.split("x")
                w = w[w.index("-")+1:w.index(",")]
                h = h[h.index("-")+1:h.index(",")]
                return f"{w}x{h}"
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
            return f"{bw}x{bh}"

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
    for device in Path("/dev/").glob("video*"):
        options = camera_info(device, hide_error=True)
        if not options:
            continue
        if 'h264' in options:
            current_best = (device, options)
        elif 'h264' not in current_best[1]:
            current_best = (device, options)
    if not current_best[0]:
        return "/dev/video0", "h264", "1920x1080"  # Assume user will connect pi camera
    for fmt in ('h264', 'mjpeg', 'yuyv422', 'yuv420p'):
        if fmt in current_best[1]:
            return current_best[0], fmt, current_best[1][fmt]
    fmt, res = list(current_best[1].items())[0]
    return current_best[0], fmt, res


def program_installations(compile_ffmpeg, install_ffmpeg, extra_libs, install_type):
    log.info("Installing nginx")
    apt("apt install -y nginx")

    ffmpeg_configures, apt_installs = [], []
    possible_installs = {0: minimal_ffmpeg_config, 1: standard_ffmpeg_config, 2: all_ffmpeg_config}
    if install_type not in possible_installs:
        raise Exception(f"Unexpected install type {install_type}")

    for f, a in possible_installs[install_type]:
        ffmpeg_configures.append(f)
        apt_installs.append(a)

    ffmpeg_libs = "{}".format(" ".join(ffmpeg_configures))

    if compile_ffmpeg:
        if disable_overwrite and (here / "FFmpeg" / "ffmpeg").exists():
            log.info(f"FFmpeg is already compiled at {here / 'FFmpeg' / 'ffmpeg'}")
            if install_ffmpeg:
                install_compiled_ffmpeg()
            return
        log.info("Installing FFmpeg requirements")
        apt("apt install -y git checkinstall build-essential {}".format(" ".join(apt_installs)))

        if not (here / "FFmpeg").exists():
            log.info("Grabbing FFmpeg")
            cmd("git clone https://github.com/FFmpeg/FFmpeg.git --depth 1")
        else:
            log.info("FFmpeg exists: updating FFmpeg via git pull")
            cmd("git pull", cwd=here / "FFmpeg")

        log.info("Configuring FFmpeg")
        cmd(
            f"./configure {raspberry_proc_info()} --target-os=linux "
            f"--libdir=/usr/lib/arm-linux-gnueabihf --incdir=/usr/include/arm-linux-gnueabihf "
            '--extra-cflags="-I/usr/local/include -I/usr/include/arm-linux-gnueabihf" '
            '--extra-ldflags="-L/usr/local/lib -L/usr/lib/arm-linux-gnueabihf" '
            '--extra-libs="-lpthread -lm" '
            "--enable-static --disable-shared --disable-debug --enable-gpl --enable-version3 --enable-nonfree  "
            f"{ffmpeg_libs} {extra_libs}",
            cwd=here / "FFmpeg",
        )

        log.info("Building FFmpeg (This will take a while)")
        cmd(f"make {'-j4' if raspberry_proc_info(cores_only=True) >= 4 else ''}", cwd=here / "FFmpeg")
        if install_ffmpeg:
            install_compiled_ffmpeg()


def ensure_library_dir():
    lib_path = Path(here, "ffmpeg-libraries")
    lib_path.mkdir(exist_ok=True)
    return lib_path


def install_fdk_aac():
    if Path("/usr/local/lib/libfdk-aac.la").exists():
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
    cmd("make install", cwd=sub_dir)
    return "--enable-libfdk-aac"


def install_avisynth():
    if Path("/usr/local/include/avisynth/avisynth_c.h").exists():
        log.info("AviSynth headers already built")
        return "--enable-avisynth"

    log.info("Building AviSynth headers")
    lib_dir = ensure_library_dir()
    sub_dir = lib_dir / "AviSynthPlus"
    if sub_dir.exists():
        cmd("git pull", cwd=sub_dir)
    else:
        cmd(f"git clone --depth 1 https://github.com/AviSynth/AviSynthPlus.git AviSynthPlus", cwd=lib_dir)
    build_dir = sub_dir / "avisynth-build"
    build_dir.mkdir(exist_ok=True)
    cmd("cmake ../ -DHEADERS_ONLY:bool=on", cwd=build_dir)
    cmd("make install", cwd=build_dir)
    return "--enable-avisynth"


def install_libxavs():
    if shutil.which("xavs"):
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
    cmd("make install", cwd=sub_dir)
    return "--enable-libxavs"

# svn co https://svn.code.sf.net/p/xavs/code/trunk xavs
def install_dav1d():
    if shutil.which("dav1d"):
        log.info("dav1d already built")
        return "--enable-libdav1d"

    log.info("Building dav1d")
    lib_dir = ensure_library_dir()
    sub_dir = lib_dir / "dav1d"
    build_dir = sub_dir / "build"
    build_dir.mkdir(exist_ok=True)

    apt("apt install -y meson ninja-build")
    if sub_dir.exists():
        cmd("git pull", cwd=sub_dir)
    else:
        cmd(f"git clone --depth 1 https://code.videolan.org/videolan/dav1d.git dav1d", cwd=lib_dir)
    cmd("meson ..", cwd=build_dir)
    cmd("ninja", cwd=build_dir)
    cmd("ninja install", cwd=build_dir)
    return "--enable-libdav1d"


def install_zimg():
    if Path("/usr/local/lib/libzimg.la").exists():
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
    cmd("make install", cwd=sub_dir)
    return "--enable-libzimg"


def install_kvazaar():
    if shutil.which("kvazaar"):
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
    cmd("make install", cwd=sub_dir)
    return "--enable-libkvazaar"


# vmaf giving error: test/meson.build:7:0: ERROR:  Include directory to be added is not an include directory object.
# def install_vmaf():
#     # figure out how to detect vmaf installed
#     lib_dir = ensure_library_dir()
#     sub_dir = lib_dir / "vmaf" / "libvmaf"
#
#     log.info("Building libvmaf")
#     apt("apt install -y meson ninja-build doxygen")
#     if (lib_dir / "vmaf").exists():
#         cmd("git pull", cwd=(lib_dir / "vmaf"))
#     else:
#         cmd(f"git clone --depth 1 https://github.com/ultravideo/kvazaar.git kvazaar", cwd=lib_dir)
#     cmd("meson build --buildtype release", cwd=sub_dir)
#     cmd("ninja -vC build", cwd=sub_dir)
#     cmd("ninja -vC build install", cwd=sub_dir)
#     return "--enable-libvmaf"


def install_compiled_ffmpeg():
    log.info("Installing FFmpeg")
    apt(f"apt remove ffmpeg -y {'' if disable_overwrite else '--allow-change-held-packages'} ")
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
    ffmpeg_command = ("ffmpeg -nostdin -hide_banner -loglevel error "
                      f"-f v4l2 -input_format {input_format} -s {video_size} -i {video_device} "
                      "-c:v copy -seg_duration 0.2 -remove_at_exit 1 -window_size 10 -f dash -hls_playlist 1 "
                      "/dev/shm/streaming/manifest.mpd")
    systemd_contents = f"""# /etc/systemd/system/encode_webcam.service
[Unit]
Description=encode_webcam
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


def start_services(on_reboot_file):
    cmd(f"/bin/bash {on_reboot_file}")
    cmd("systemctl daemon-reload")
    cmd("systemctl start encode_webcam")
    cmd("systemctl enable encode_webcam")


def show_services():
    ips = run("hostname -I", shell=True, stdout=PIPE).stdout.decode("utf-8")
    hostname = run("hostname", shell=True, stdout=PIPE).stdout.decode("utf-8").strip()
    for host in ips.split() + [hostname]:
        log.info(f"Try viewing the stream at http://{host}/streaming")


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

    its = ("min", "standard", "all")
    install_type = its.index(args.install_type.lower())
    if install_type < 0:
        raise Exception("Incorrect install type selected")
    log.info(f"Performing '{its[install_type]}' install")

    if not args.disable_compile_ffmpeg and install_type >= 1:
        apt("apt install -y git build-essential")
        extra_libs = []
        if install_type >= 1 and not args.disable_fdk_aac:
            extra_libs.append(install_fdk_aac())
        if install_type >= 1 and not args.disable_avisynth:
            extra_libs.append(install_avisynth())
        if install_type >= 2 and not args.disable_zimg:
            extra_libs.append(install_zimg())
        if install_type >= 2 and not args.disable_dav1d:
            extra_libs.append(install_dav1d())
        if install_type >= 2 and not args.disable_kvazaar:
            extra_libs.append(install_kvazaar())
        if install_type >= 2 and not args.disable_libxavs:
            extra_libs.append(install_libxavs())

    cmd("ldconfig")

    program_installations(
        not args.disable_compile_ffmpeg,
        not args.disable_install_ffmpeg,
        extra_libs=" ".join(extra_libs),
        install_type=install_type,
    )
    update_rc_local_file(on_reboot_file=on_reboot_file)
    install_index_file(index_file=index_file, video_size=args.video_size)
    install_on_reboot_file(on_reboot_file=on_reboot_file, index_file=index_file)
    install_systemd_file(
        systemd_file=systemd_file, input_format=args.input_format, video_size=args.video_size, video_device=args.device,
    )
    start_services(on_reboot_file=on_reboot_file)
    log.info("Install complete!")
    show_services()


if __name__ == "__main__":
    main()
