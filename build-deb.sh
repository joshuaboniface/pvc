#!/bin/sh
ver="0.1"
git pull
rm ../pvc_*
dh_make -p pvc_${ver} --createorig --single --yes
dpkg-buildpackage -us -uc
dh_clean