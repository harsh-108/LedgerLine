#!/data/data/com.termux/files/usr/bin/bash
# Register the boot script with Termux:Boot and start the supervisor now.
set -e
APP_DIR="${APP_DIR:-$HOME/ledgerline}"
mkdir -p "$HOME/.termux/boot"
cp "$APP_DIR/deploy/termux/boot.sh" "$HOME/.termux/boot/ledgerline.sh"
chmod +x "$HOME/.termux/boot/ledgerline.sh" "$APP_DIR"/deploy/termux/*.sh
echo "installed ~/.termux/boot/ledgerline.sh"
echo "Reminder: open the Termux:Boot app once, and turn OFF battery optimisation"
echo "for both Termux and Termux:Boot, or Android will not run it at boot."
bash "$HOME/.termux/boot/ledgerline.sh"
echo "supervisor started — log: tail -f $APP_DIR/data/server.log"
