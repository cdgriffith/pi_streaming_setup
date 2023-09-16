# -*- coding: utf-8 -*-
"""
If you will be compiling while running over SSH, please use in a background terminal like "tmux" or "screen".

Be aware, this will build a NON-REDISTRIBUTABLE FFmpeg.
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
__version__ = "1.7"

log = logging.getLogger("compile_ffmpeg")
command_log = logging.getLogger("compile_ffmpeg.command")
CMD_LVL = 15
logging.addLevelName(CMD_LVL, "CMD")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)-12s  %(levelname)-8s %(message)s",
    filename=f"compile_ffmpeg_{datetime.datetime.now().strftime('%Y%M%d_%H%M%S')}.log",
)

sh = logging.StreamHandler(sys.stdout)
log.setLevel(logging.DEBUG)
command_log.setLevel(logging.DEBUG)
log.addHandler(sh)

here = Path(__file__).parent
disable_overwrite = False
run_as = "root"
rebuild_all = False
detected_arch = None
detected_model = ""
detected_cores = 1

# Different levels of FFmpeg configurations
# They are set to be in format ( configuration flag(s), apt library(s) )

# Minimal h264, x264, alsa sound and fonts
minimal_ffmpeg_config = [
    ("--enable-libx264", "libx264-dev"),
    ("--enable-indev=alsa --enable-outdev=alsa", "libasound2-dev"),
    ("--enable-libfreetype", "libfreetype6-dev fonts-freefont-ttf"),
]

all_ffmpeg_config = minimal_ffmpeg_config + [
    ("--enable-libx265", "libx265-dev"),
    ("--enable-libvpx", "libvpx-dev"),
    ("--enable-libmp3lame", "libmp3lame-dev"),
    ("--enable-libvorbis", "libvorbis-dev"),
    ("--enable-libopus", "libopus-dev"),
    ("--enable-libtheora", "libtheora-dev"),
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
    parser = ArgumentParser(prog="compile_ffmpeg", description=f"compile_ffmpeg version {__version__}")
    parser.add_argument("-v", "--version", action="store_true")
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Minimal FFmpeg compile including h264, x264, alsa sound and fonts",
    )
    parser.add_argument(
        "--run-as", default="root", help="compile programs as provided user (suggested 'pi', defaults to 'root')"
    )
    parser.add_argument("--disable-fdk-aac", action="store_true", help="Normally installed on full install")
    parser.add_argument("--disable-avisynth", action="store_true", help="Normally installed on full install")
    parser.add_argument("--disable-dav1d", action="store_true", help="Normally installed on full install")
    parser.add_argument("--disable-zimg", action="store_true", help="Normally installed on full install")
    parser.add_argument("--disable-kvazaar", action="store_true", help="Normally installed on full install")
    parser.add_argument("--disable-libxavs", action="store_true", help="Normally installed on full install")
    parser.add_argument("--disable-libsrt", action="store_true", help="Normally installed on full install")
    parser.add_argument("--rebuild-all", action="store_true", help="Recompile all libraries")
    parser.add_argument("--safe", action="store_true", help="disable overwrite of existing or old scripts")
    parser.add_argument("--install", action="store_true", help="Run make install to put it in /usr/local/bin")
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
    return {x["field"].replace(":", ""): x["data"] for x in results["lscpu"]}


def raspberry_proc_info(cores_only=False):
    global detected_arch, detected_model, detected_cores

    if detected_arch:
        arch = detected_arch
        results = {}
        if cores_only:
            return detected_cores
    else:
        results = lscpu_output()
        arch = results["architecture"]
        detected_model = results["model name"]
        detected_cores = int(results.get("cpu(s)", 1))
        if cores_only:
            return detected_cores
        log.info(f"Model Info: {Path('/proc/device-tree/model').read_text()}")
        if "architecture" not in results:
            log.warning(f"Could not grab architecture information from lscpu, defaulting to armhf: {results}")
            return "--arch=armhf "
    if "armv7" in arch:
        detected_arch = "armv7"
        if "cortex-a72" in detected_model:
            # Raspberry Pi 4 Model B
            log.info("Optimizing for cortex-a72 processor")
            return (
                "--arch=armv7 --cpu=cortex-a72 --enable-neon "
                "--extra-cflags='-mtune=cortex-a72 -mfpu=neon-vfpv4 -mfloat-abi=hard'"
            )
        if "cortex-a53" in detected_model:
            # Raspberry Pi 3 Model B
            log.info("Optimizing for cortex-a53 processor")
            return (
                "--arch=armv7 --cpu=cortex-a53 --enable-neon "
                "--extra-cflags='-mtune=cortex-a53 -mfpu=neon-vfpv4 -mfloat-abi=hard'"
            )
        log.info("Using architecture 'armv7'")
        return "--arch=armv7 --enable-neon "
    if "armv6" in arch:
        # Raspberry Pi Zero
        detected_arch = "armv6"
        log.info("Using architecture 'armv6'")
        return "--arch=armv6"
    if "aarch64" in arch:
        # Using new raspberry pi 64 bit OS
        detected_arch = "aarch64"
        log.info("Using architecture 'aarch64'")
        if "cortex-a72" in detected_model:
            # Raspberry Pi 4 Model B
            log.info("Optimizing for cortex-a72 processor")
            return "--arch=aarch64 --cpu=cortex-a72 --enable-neon " "--extra-cflags='-mtune=cortex-a72'"
        return "--arch=aarch64"

    log.warning(f"Could not grab architecture information from lscpu, defaulting to armhf: {results}")
    return "--arch=armhf"


def compile_ffmpeg(extra_libs, minimal_install=False, install=False):
    ffmpeg_configures, apt_installs = [], []

    if detected_arch != "aarch64":
        all_ffmpeg_config.append(("--enable-libopenjpeg", "libopenjpeg-dev libopenjp2-7-dev"))
        # all_ffmpeg_config.append(("--enable-mmal", "")) This just breaks anymore?
    else:
        all_ffmpeg_config.append(("--enable-libopenjpeg", "libopenjp2-7-dev"))

    for f, a in all_ffmpeg_config if not minimal_install else minimal_ffmpeg_config:
        ffmpeg_configures.append(f)
        apt_installs.append(a)

    ffmpeg_libs = "{}".format(" ".join(ffmpeg_configures))
    processor_info = raspberry_proc_info()  # Needs to be here to proper error before the apt install

    log.info("Installing FFmpeg requirements")
    apt("apt install -y git build-essential {}".format(" ".join(apt_installs)))

    ffmpeg_dir = here / "FFmpeg"
    if not ffmpeg_dir.exists():
        log.info("Grabbing FFmpeg")
        cmd("git clone https://github.com/FFmpeg/FFmpeg.git FFmpeg --depth 1", cwd=here)
    else:
        log.info("FFmpeg exists: updating FFmpeg via git pull")
        cmd("git pull", cwd=ffmpeg_dir)

    # with open(ffmpeg_dir / "libavcodec" / "v4l2_m2m_enc.c", "r+") as fd:
    #     contents = fd.readlines()
    #     insert = -1
    #     for i, line in enumerate(contents):
    #         if "v4l2_set_ext_ctrl(s, MPEG_CID(GOP_SIZE)" in line:
    #             if "REPEAT_SEQ_HEADER" not in contents[i + 1]:
    #                 insert = i
    #                 break
    #     if insert > 0:
    #         log.info("Inserting repeat parameter sets into v4l2_m2m_enc.c")
    #         contents.insert(
    #             insert, '    v4l2_set_ext_ctrl(s, MPEG_CID(REPEAT_SEQ_HEADER), 1,"repeat parameter sets", 1);\n'
    #         )
    #     fd.seek(0)
    #     fd.writelines(contents)

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
    if install:
        cmd("make install", cwd=ffmpeg_dir, demote=False)


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
    cmd("make VersionGen install", cwd=build_dir, demote=False)
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

    # Fix issues on aarch64
    # os.unlink(sub_dir / "config.sub")
    # os.unlink(sub_dir / "config.guess")
    #
    # with urlopen("http://cvs.savannah.gnu.org/viewvc/*checkout*/config/config/config.sub") as response, open(sub_dir / "config.sub", "wb") as out_file:
    #     shutil.copyfileobj(response, out_file)
    #
    # with urlopen("http://cvs.savannah.gnu.org/viewvc/*checkout*/config/config/config.guess") as response, open(sub_dir / "config.guess", "wb") as out_file:
    #     shutil.copyfileobj(response, out_file)
    # cmd("chmod +x config.*", cwd=sub_dir, demote=False)

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

    apt("apt install -y libcpuinfo-dev")

    log.info("Building libzimg")
    lib_dir = ensure_library_dir()
    sub_dir = lib_dir / "zimg"
    if sub_dir.exists():
        cmd("git pull", cwd=sub_dir)
    else:
        cmd(f"git clone https://github.com/sekrit-twc/zimg.git zimg", cwd=lib_dir)

    # Needed to fix
    # *** No rule to make target 'graphengine/graphengine/cpuinfo.cpp',
    # needed by 'graphengine/graphengine/libzimg_internal_la-cpuinfo.lo'.
    shutil.rmtree(sub_dir / "graphengine", ignore_errors=True)
    cmd("git submodule update --recursive --init", cwd=sub_dir)

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


def ensure_library_dir():
    lib_path = Path(here, "ffmpeg-libraries")
    return user_dir(lib_path)


def user_dir(new_path):
    new_path.mkdir(exist_ok=True)
    pw_record = pwd.getpwnam(run_as)
    os.chown(new_path, pw_record.pw_uid, pw_record.pw_gid)
    return new_path


def main():
    global disable_overwrite, run_as, rebuild_all

    # Run before args to make sure we have the right processor info for codec format
    raspberry_proc_info()

    args = parse_arguments()
    if args.version:
        print(f"{__version__}")
        sys.exit(0)

    if os.geteuid() != 0:
        log.critical("This script requires root / sudo privileges")
        sys.exit(1)

    if args.run_as != "root":
        run_as = args.run_as
        try:
            pwd.getpwnam(run_as)
        except KeyError:
            log.critical(f"Cannot run as {run_as} as that user does not exist!")
            sys.exit(1)

    log.info(f"Starting compile_ffmpeg {__version__}")
    log.debug(f"Using arguments: {vars(args)}")

    if args.safe:
        disable_overwrite = True

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
            if detected_arch == "aarch64":
                log.error("Cannot install libxavs on aarch64")
            else:
                extra_libs.append(install_libxavs())
        if not args.disable_libsrt:
            extra_libs.append(install_srt())
        cmd("ldconfig", demote=False)
    compile_ffmpeg(extra_libs=" ".join(extra_libs), minimal_install=args.minimal, install=args.install)

    log.info("Compile complete!")


if __name__ == "__main__":
    main()
