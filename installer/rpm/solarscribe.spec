############################################################
# SolarScribe - RPM spec (Fedora / RHEL / openSUSE)
#
# Built by the CI Linux RPM job on a Fedora container:
#   rpmbuild -bb --define "_version <v>" --define "_with_sdk 1" \
#       installer/rpm/solarscribe.spec
# Output: solarscribe-<v>-1.<dist>.noarch.rpm
#
# The package uses the SYSTEM Python and lets RPM's automatic Python
# dependency generator read the imports, so Requires is the distribution's own
# python3dist(...) set. PySide6, numpy and platformdirs are hard dependencies.
# INDI is a Recommends, not a Requires: the mount backend is external (ADR-019)
# and the app degrades to the simulator when indiserver is not running.
#
# The camera SDKs are COPIES of installer/vendor/bundle/linux, which
# prepare_vendor.py fills with the licence-approved set only. _with_sdk is 0
# unless the CI has something to ship, so a source build without SDKs still
# produces an installable package that degrades gracefully (ADR-017).
############################################################

%define version %{?_version}%{!?_version:0.0.0}
%define with_sdk %{?_with_sdk}%{!?_with_sdk:0}
%define with_firmware %{?_with_firmware}%{!?_with_firmware:0}

%global debug_package %{nil}

Name:           solarscribe
Version:        %{version}
Release:        1%{?dist}
Summary:        Capture application for a solar spectroheliograph (SHG)
License:        GPL-3.0-or-later
URL:            https://github.com/irydeo/solarscribe
Source0:        %{name}-%{version}.tar.gz
# The Python code is architecture independent, but a bundle with vendor SDKs
# is not: those are x86_64 binaries. A source build without a bundle stays
# noarch so it can be installed anywhere.
%if %{with_sdk}
BuildArch:      x86_64
%else
BuildArch:      noarch
%endif
BuildRequires:  python3-devel
Recommends:     indi
Recommends:     fxload

%description
SolarScribe opens the camera and the mount, measures live and runs the SHG
scan, and leaves the SER files and logs ready for post-processing. The mount
is ASCOM COM on Windows and INDI on Linux; the camera is a vendor SDK loaded
dynamically. A missing SDK or mount server is reported and the application
keeps working with what is present.

%prep
%setup -q

%build
# Pure Python: nothing to compile.

%install
rm -rf %{buildroot}
install -d %{buildroot}%{python3_sitelib}
cp -a solarscribe %{buildroot}%{python3_sitelib}/solarscribe
find %{buildroot}%{python3_sitelib} -name '__pycache__' -type d \
    -exec rm -rf {} +
# The .ts catalogues are the translation SOURCE; only the compiled .qm files
# are runtime data (ADR-016).
find %{buildroot}%{python3_sitelib} -name '*.ts' -delete

# The version must live where importlib.metadata.version("solarscribe") reads
# it; a bare copy of the tree reports the "0.0.0" fallback and the version in
# session_meta.json would be a lie (ADR-017).
install -d %{buildroot}%{python3_sitelib}/solarscribe-%{version}.dist-info
printf 'Metadata-Version: 2.1\nName: solarscribe\nVersion: %{version}\n' \
    > %{buildroot}%{python3_sitelib}/solarscribe-%{version}.dist-info/METADATA
install -d %{buildroot}%{_datadir}/solarscribe
printf '%s\n' '%{version}' > %{buildroot}%{_datadir}/solarscribe/version

install -d %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/solarscribe <<'EOF'
#!/bin/sh
# The current native loader asks ctypes for the bare library name, so the
# private SDK folder must be on the dynamic loader path.
SDK_ROOT=/usr/lib/solarscribe/sdk
if [ -d "$SDK_ROOT" ]; then
    for d in "$SDK_ROOT"/*; do
        [ -d "$d" ] || continue
        LD_LIBRARY_PATH="$d${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    done
    export LD_LIBRARY_PATH
fi
exec python3 -m solarscribe "$@"
EOF
chmod 0755 %{buildroot}%{_bindir}/solarscribe

install -d %{buildroot}%{_datadir}/applications
install -m 0644 installer/io.github.irydeo.solarscribe.desktop \
    %{buildroot}%{_datadir}/applications/io.github.irydeo.solarscribe.desktop
install -d %{buildroot}%{_datadir}/metainfo
install -m 0644 installer/io.github.irydeo.solarscribe.metainfo.xml \
    %{buildroot}%{_datadir}/metainfo/io.github.irydeo.solarscribe.metainfo.xml

for s in 16 32 48 64 128 256; do
    install -d %{buildroot}%{_datadir}/icons/hicolor/${s}x${s}/apps
    install -m 0644 installer/icons/solarscribe-${s}.png \
        %{buildroot}%{_datadir}/icons/hicolor/${s}x${s}/apps/solarscribe.png
done

install -d %{buildroot}%{_datadir}/licenses/%{name}
install -m 0644 LICENSE %{buildroot}%{_datadir}/licenses/%{name}/LICENSE
cp -a installer/licenses %{buildroot}%{_datadir}/licenses/%{name}/sdk-licenses
cp -a installer/sdk-manifest.json \
    %{buildroot}%{_datadir}/licenses/%{name}/sdk-licenses/sdk-manifest.json
if [ -f installer/vendor/bundle/linux/MANIFEST.json ]; then
    cp -a installer/vendor/bundle/linux/MANIFEST.json \
        %{buildroot}%{_datadir}/licenses/%{name}/sdk-licenses/bundle-MANIFEST.json
fi

install -d %{buildroot}%{_datadir}/doc/%{name}
cp -a docs/. %{buildroot}%{_datadir}/doc/%{name}/
install -m 0644 installer/PREREQUISITES.txt \
    %{buildroot}%{_datadir}/doc/%{name}/PREREQUISITES.txt

# udev rules are always useful. The QHY firmware rule only goes in with the
# firmware itself, otherwise udev would call fxload on a missing file.
install -d %{buildroot}%{_prefix}/lib/udev/rules.d
install -m 0644 installer/udev/99-solarscribe-cameras.rules \
    %{buildroot}%{_prefix}/lib/udev/rules.d/99-solarscribe-cameras.rules

%if %{with_sdk}
if [ -d installer/vendor/bundle/linux ]; then
    install -d %{buildroot}%{_prefix}/lib/solarscribe/sdk
    for sdk in installer/vendor/bundle/linux/*; do
        [ -d "$sdk" ] || continue
        [ "$(basename "$sdk")" = firmware ] && continue
        cp -a "$sdk" %{buildroot}%{_prefix}/lib/solarscribe/sdk/
    done
fi
if [ "%{with_firmware}" = "1" ] && [ -d installer/vendor/bundle/linux/firmware/qhy ]; then
    install -d %{buildroot}%{_prefix}/lib/firmware/qhy
    cp -a installer/vendor/bundle/linux/firmware/qhy/. \
        %{buildroot}%{_prefix}/lib/firmware/qhy/
    install -m 0644 installer/udev/85-solarscribe-qhy.rules \
        %{buildroot}%{_prefix}/lib/udev/rules.d/85-solarscribe-qhy.rules
fi
%endif

%post
if ! command -v indiserver >/dev/null 2>&1; then
    echo "SolarScribe: indiserver is not installed; the mount backend will" \
         "report it as missing. Install the indi package to use INDI." >&2
fi
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger --subsystem-match=usb || true
fi

%postun
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger --subsystem-match=usb || true
fi

%files
%{python3_sitelib}/solarscribe
%{python3_sitelib}/solarscribe-%{version}.dist-info
%{_bindir}/solarscribe
%{_datadir}/applications/io.github.irydeo.solarscribe.desktop
%{_datadir}/metainfo/io.github.irydeo.solarscribe.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/solarscribe.png
%license %{_datadir}/licenses/%{name}/LICENSE
%{_datadir}/licenses/%{name}/sdk-licenses
%{_datadir}/doc/%{name}
%{_datadir}/solarscribe/version
%{_prefix}/lib/udev/rules.d/99-solarscribe-cameras.rules

%if %{with_sdk}
%{_prefix}/lib/solarscribe/sdk
%if %{with_firmware}
%{_prefix}/lib/firmware/qhy
%{_prefix}/lib/udev/rules.d/85-solarscribe-qhy.rules
%endif
%endif

%changelog
* Fri Nov 06 2026 Francisco Jose Calvo Fernandez <irydeo@users.noreply.github.com> - %{version}-1
- Package the SolarScribe capture application.
