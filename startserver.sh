if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit
fi
echo "Copying conf.yaml where it will be readen by gonetem server."
cp ./config.yaml /etc/gonetem/config.yaml
echo "Starting gonetem server."
gonetem-server
