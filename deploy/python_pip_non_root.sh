#!/bin/sh
echo "Downloading source code"
wget https://www.python.org/ftp/python/2.7.13/Python-2.7.13.tgz
echo "Decompressing"
tar -xzf Python-2.7.13.tgz
cd Python-2.7.13
mkdir -p $HOME/bin
echo "Configuring"
./configure --prefix="$HOME"
echo "Making"
make
echo "Installing"
make install
export PATH=$HOME/bin:$PATH
echo "Downloading pip"
wget https://bootstrap.pypa.io/get-pip.py
if [ $? -ne 0 ]; then
    echo "Cannot download get-pip.py, now try another source"
    wget --no-check-certificate https://raw.githubusercontent.com/BioQueue/dependent-packages-backup/master/get-pip.py
    if [ $? -ne 0 ]; then
        echo "Cannot download get-pip.py, now try another source"
        wget http://bioqueue.nefu.edu.cn/get-pip.py
        if [ $? -ne 0 ]; then
            echo "Cannot download get-pip.py, please download it manually"
            exit
        fi
    fi
fi
$HOME/bin/python get-pip.py