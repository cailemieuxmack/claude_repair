FROM ubuntu:20.04
ENV DEBIAN_FRONTEND noninteractive
ENV LC_ALL C.UTF-8
ENV LANG C.UTF-8

# create docker user
RUN apt-get update \
 && apt-get install --no-install-recommends -y sudo patch locales \
 && useradd -ms /bin/bash docker \
 && echo 'docker ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers \
 && adduser docker sudo \
 && apt-get clean \
 && mkdir -p /home/docker \
 && sudo chown -R docker /home/docker \
 && sudo chown -R docker /usr/local/bin \
 && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
USER docker

# Set the locale to avoid prompting during dependency install
RUN sudo ln -sf /usr/share/zoneinfo/EST /etc/localtime
# RUN sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && \
RUN locale-gen
ENV LANG=en_US.UTF-8 \
 LANGUAGE=en_US:en \
 LC_ALL=en_US.UTF-8

# install dependencies
RUN sudo apt-get update \
 && sudo apt-get install -y --no-install-recommends \
      gcc-10 \
      g++-10 \
     #  libboost-filesystem-dev \
      gcovr \
      libc6-dev \
      bc \
      gdb \
      python3 \
      python3-pip \
      python3-setuptools \
      acl \
 && sudo apt-get clean \
 && sudo rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# upgrade pip to a compatible version and install numpy
RUN python3 -m pip install --user --upgrade pip==20.3.4 \
 && python3 -m pip install --user numpy

WORKDIR /experiment
COPY test_driver.cpp /experiment/lib/
COPY controller.c /experiment/source/
COPY controller.h /experiment/
# COPY controller_sanity.c /experiment/source/
COPY test.sh /experiment
COPY check_distance.py /experiment
COPY test /experiment/test
RUN sudo chown -R docker /experiment

# Try to make it so that you can rm from /tmp easilly
# RUN sudo apt-get update \
#  && sudo apt-get install -y acl

RUN sudo chattr -i /tmp \
 && sudo chown docker /tmp 
#  && sudo chmod 2777 /tmp 

RUN sudo setfacl -m u:docker:rwx /tmp \
 && sudo setfacl -m u:1001:rwx /tmp \
 && sudo setfacl -d -m u:docker:rwx /tmp \
 && sudo setfacl -d -m u:1001:rwx /tmp

# sudo setfacl -d -m u:docker:rwx /tmp
#  && sudo chmod +t /tmp

# # Copy the entry point script into the container
# COPY entrypoint.sh /experiment/entrypoint.sh

# # # Make the script executable
# # RUN chmod +x /experiment/entrypoint.sh

# # Set the entry point to the script
# ENTRYPOINT ["/experiment/entrypoint.sh"]