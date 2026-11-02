#!/usr/bin/env bash
# Dev helper for the Pardus test VM (run from Git Bash on the Windows host).
#
#   scripts/dev/vm.sh ip                 print the VM's IP address
#   scripts/dev/vm.sh deploy             copy this checkout to ~/pardus-clicky in the VM
#   scripts/dev/vm.sh sh 'cmd ...'       run a command inside the logged-in GNOME session
#   scripts/dev/vm.sh shot out.png       screenshot of the VM display (taken by VMware, from outside)
#   scripts/dev/vm.sh reload-ext         reload the shell extension's lib/ without logging out
#   scripts/dev/vm.sh restart            restart the Clicky app in the session
#   scripts/dev/vm.sh logs [n]           last n lines of app log + extension messages
#
# Settings can be overridden with environment variables; defaults match the
# VM this project was started on.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VMRUN="${VMRUN:-/c/Program Files/VMware/VMware Workstation/vmrun.exe}"
VMX="${VMX:-C:\\Users\\eminb\\Documents\\Virtual Machines\\Pardus 25\\Pardus 25.vmx}"
VM_USER="${VM_USER:-pardus}"
VM_PASS="${VM_PASS:-pardus}"
KEY="${KEY:-$ROOT/secrets/vm_ed25519}"
IP_CACHE="$ROOT/secrets/vm_ip"

vm_ip() {
    if [[ -n "${VM_IP:-}" ]]; then echo "$VM_IP"; return; fi
    if [[ -f "$IP_CACHE" ]] && ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=3 "$VM_USER@$(cat "$IP_CACHE")" true 2>/dev/null; then
        cat "$IP_CACHE"; return
    fi
    local ip
    ip="$("$VMRUN" -T ws getGuestIPAddress "$VMX" -wait | tr -d '\r')"
    echo "$ip" > "$IP_CACHE"
    echo "$ip"
}

# Environment of the graphical session, so GUI programs started over SSH land
# on the user's desktop and reach the session bus.
SESSION_ENV='export XDG_RUNTIME_DIR=/run/user/$(id -u); export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus; export WAYLAND_DISPLAY=wayland-0 DISPLAY=:0; export XAUTHORITY=$(ls $XDG_RUNTIME_DIR/.mutter-Xwaylandauth.* 2>/dev/null | head -1); export XDG_SESSION_TYPE=wayland XDG_CURRENT_DESKTOP=GNOME;'

vm_ssh() {
    ssh -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$VM_USER@$(vm_ip)" "$SESSION_ENV $*"
}

cmd="${1:-help}"; shift || true
case "$cmd" in
    ip) vm_ip ;;
    deploy)
        ip="$(vm_ip)"
        tar -C "$ROOT" --exclude=.git --exclude=secrets --exclude='__pycache__' --exclude='*.pyc' -czf - . \
            | ssh -i "$KEY" -o BatchMode=yes "$VM_USER@$ip" 'mkdir -p ~/pardus-clicky && tar -xzf - -C ~/pardus-clicky'
        if [[ -f "$ROOT/secrets/openai.key" ]]; then
            ssh -i "$KEY" -o BatchMode=yes "$VM_USER@$ip" 'mkdir -p ~/.config/pardus-clicky && umask 077 && cat > ~/.config/pardus-clicky/openai.key' < "$ROOT/secrets/openai.key"
        fi
        echo "deployed to $VM_USER@$ip:~/pardus-clicky"
        ;;
    sh) vm_ssh "$@" ;;
    shot)
        out="${1:-shot.png}"
        "$VMRUN" -T ws -gu "$VM_USER" -gp "$VM_PASS" captureScreen "$VMX" "$(cygpath -w "$(realpath -m "$out")")"
        echo "$out"
        ;;
    reload-ext)
        vm_ssh 'gdbus call --session --dest tr.org.pardus.clicky.Shell --object-path /tr/org/pardus/clicky/Shell --method tr.org.pardus.clicky.Shell.Reload >/dev/null && echo reloaded'
        ;;
    restart)
        # The pattern must not match this shell's own command line, or pkill kills the SSH session.
        vm_ssh 'pkill -f "python3 -m [p]ardus_clicky" 2>/dev/null; sleep 0.5; cd ~/pardus-clicky && (setsid nohup bin/pardus-clicky > ~/.cache/pardus-clicky.log 2>&1 < /dev/null &) ; sleep 2; tail -n 5 ~/.cache/pardus-clicky.log'
        ;;
    logs)
        n="${1:-40}"
        vm_ssh "tail -n $n ~/.cache/pardus-clicky.log 2>/dev/null; echo '--- shell'; journalctl --user -b --no-pager -o cat -n 400 2>/dev/null | grep -i clicky | tail -n $n"
        ;;
    *) sed -n '2,14p' "$0" ;;
esac
