# 远端服务器只读体检脚本（不改任何东西，可反复执行）
# 用法：在 Xshell 连上服务器后，整段粘贴回车，把输出贴回给对话

echo "### OS"; cat /etc/os-release 2>/dev/null | head -3
echo "### CPU"; nproc
echo "### MEM"; free -h
echo "### DISK"; df -h | head -8
echo "### SWAP"; swapon --show 2>/dev/null || echo none
echo "### LISTEN PORTS"; ss -tlnp 2>/dev/null | head -30
echo "### DOCKER"; docker --version 2>/dev/null || echo none; docker ps 2>/dev/null | head
echo "### RUNNING SERVICES"; systemctl list-units --type=service --state=running --no-pager 2>/dev/null | head -25
echo "### STACKS"; for c in nginx apache2 mysql mariadb redis-server postgresql pm2 java node python3 docker; do command -v "$c" >/dev/null && echo "$c: $(command -v "$c")"; done
echo "### CRON"; crontab -l 2>/dev/null | head -15
echo "### DIRS"; ls -la /opt /srv /www /data /home 2>/dev/null | head -40
echo "### IP"; curl -s --max-time 5 ifconfig.me; echo
