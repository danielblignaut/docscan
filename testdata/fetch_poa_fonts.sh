#!/bin/sh
# Fonts for the proof-of-address generators (SIL Open Font License 1.1, and the
# Ubuntu Font Licence for Ubuntu), from github.com/google/fonts, into
# /tmp/docscan-poa/fonts. Not redistributed here.
#   training extras: Lato, PT Sans, PT Serif, Fira Sans, Barlow, Ubuntu, Crimson Text, IBM Plex Mono
#   lockbox only:    Titillium Web, Oxygen, Hind, Arvo, Space Mono
set -e
D=${1:-/tmp/docscan-poa/fonts}
B=https://github.com/google/fonts/raw/main
mkdir -p "$D"
for f in ofl/lato/Lato-Regular.ttf ofl/lato/Lato-Bold.ttf ofl/ptsans/PT_Sans-Web-Regular.ttf ofl/ptsans/PT_Sans-Web-Bold.ttf \
  ofl/ptserif/PT_Serif-Web-Regular.ttf ofl/ptserif/PT_Serif-Web-Bold.ttf ofl/firasans/FiraSans-Regular.ttf ofl/firasans/FiraSans-Bold.ttf \
  ofl/barlow/Barlow-Regular.ttf ofl/barlow/Barlow-Bold.ttf ufl/ubuntu/Ubuntu-Regular.ttf ufl/ubuntu/Ubuntu-Bold.ttf \
  ofl/crimsontext/CrimsonText-Regular.ttf ofl/crimsontext/CrimsonText-Bold.ttf ofl/ibmplexmono/IBMPlexMono-Regular.ttf \
  ofl/ibmplexmono/IBMPlexMono-Bold.ttf ofl/titilliumweb/TitilliumWeb-Regular.ttf ofl/titilliumweb/TitilliumWeb-Bold.ttf \
  ofl/oxygen/Oxygen-Regular.ttf ofl/oxygen/Oxygen-Bold.ttf ofl/hind/Hind-Regular.ttf ofl/hind/Hind-Bold.ttf \
  ofl/arvo/Arvo-Regular.ttf ofl/arvo/Arvo-Bold.ttf ofl/spacemono/SpaceMono-Regular.ttf ofl/spacemono/SpaceMono-Bold.ttf; do
  [ -s "$D/$(basename $f)" ] || curl -sSfL -o "$D/$(basename $f)" "$B/$f"
done
echo "fonts in $D"
