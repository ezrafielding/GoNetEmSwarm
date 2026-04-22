FROM ubuntu:22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    iproute2 \
    iputils-ping \
    net-tools \
    tcpdump \
    netcat-openbsd \
    python3 \
    python3-pip \
    curl \
    vim \
    nano \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages for distributed computing
RUN pip3 install \
    numpy \
    matplotlib \
    netifaces

# Create application directory
WORKDIR /app

# Create directories for algorithms and scripts
RUN mkdir -p /usr/lib/algorithms /usr/lib/scripts /usr/local/logs


COPY ./scripts/setup-network.py /usr/lib/scripts/setup-network.py
RUN chmod +x /usr/lib/scripts/setup-network.py

COPY ./algorithms/udpservices.py /usr/lib/algorithms/udpservices.py
RUN chmod +x /usr/lib/algorithms/udpservices.py

COPY ./algorithms/satellite.py /usr/lib/algorithms/satellite.py
RUN chmod +x /usr/lib/algorithms/satellite.py

# COPY ./algorithms/leader_test.py /usr/lib/algorithms/leader_test.py
# RUN chmod +x /usr/lib/algorithms/leader_test.py

# COPY ./algorithms/crdt_test.py /usr/lib/algorithms/crdt_test.py
# COPY ./algorithms/wordlist.txt /usr/local/wordlist.txt
# RUN chmod +x /usr/lib/algorithms/crdt_test.py

COPY ./algorithms/broadcast_test.py /usr/lib/algorithms/broadcast_test.py
RUN chmod +x /usr/lib/algorithms/broadcast_test.py

# Copy initialization script
COPY scripts/init_satellite.sh /usr/lib/scripts/iinit.sh
RUN chmod +x /usr/lib/scripts/iinit.sh

CMD ["/usr/lib/scripts/iinit.sh"]
