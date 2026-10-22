#!/bin/sh
# Fonts for testdata/poa_wide.py (SIL Open Font License 1.1, from
# github.com/google/fonts) into /tmp/docscan-poa-work/fonts. Not redistributed
# here. None of the lockbox's fonts (testdata/fetch_poa_fonts.sh) is among them.
# DEV-G draws only in SourceSerif4, Manrope, Bitter, CourierPrime and Asap;
# training in the rest.
set -e
D=${1:-/tmp/docscan-poa-work/fonts}
B=https://github.com/google/fonts/raw/main
mkdir -p "$D"
for f in ofl/opensans/OpenSans%5Bwdth,wght%5D.ttf ofl/notosans/NotoSans%5Bwdth,wght%5D.ttf ofl/sourcesans3/SourceSans3%5Bwght%5D.ttf \
  ofl/merriweather/Merriweather%5Bopsz,wdth,wght%5D.ttf ofl/montserrat/Montserrat%5Bwght%5D.ttf ofl/raleway/Raleway%5Bwght%5D.ttf \
  ofl/nunito/Nunito%5Bwght%5D.ttf ofl/worksans/WorkSans%5Bwght%5D.ttf ofl/inter/Inter%5Bopsz,wght%5D.ttf ofl/karla/Karla%5Bwght%5D.ttf \
  ofl/rubik/Rubik%5Bwght%5D.ttf ofl/cabin/Cabin%5Bwdth,wght%5D.ttf ofl/archivo/Archivo%5Bwdth,wght%5D.ttf ofl/mulish/Mulish%5Bwght%5D.ttf \
  ofl/overpass/Overpass%5Bwght%5D.ttf ofl/manrope/Manrope%5Bwght%5D.ttf ofl/librefranklin/LibreFranklin%5Bwght%5D.ttf \
  ofl/ebgaramond/EBGaramond%5Bwght%5D.ttf ofl/lora/Lora%5Bwght%5D.ttf ofl/bitter/Bitter%5Bwght%5D.ttf \
  ofl/sourceserif4/SourceSerif4%5Bopsz,wght%5D.ttf ofl/courierprime/CourierPrime-Regular.ttf ofl/courierprime/CourierPrime-Bold.ttf \
  ofl/poppins/Poppins-Regular.ttf ofl/poppins/Poppins-Bold.ttf ofl/notoserif/NotoSerif%5Bwdth,wght%5D.ttf ofl/dmsans/DMSans%5Bopsz,wght%5D.ttf \
  ofl/publicsans/PublicSans%5Bwght%5D.ttf ofl/asap/Asap%5Bwdth,wght%5D.ttf ofl/heebo/Heebo%5Bwght%5D.ttf ofl/sora/Sora%5Bwght%5D.ttf; do
  n=$(basename "$f" | sed 's/%5B.*//; s/\.ttf$//'); case "$f" in *%5B*) n="$n-VF";; esac
  [ -s "$D/$n.ttf" ] || curl -sSfL -o "$D/$n.ttf" "$B/$f"
done
echo "fonts in $D"
