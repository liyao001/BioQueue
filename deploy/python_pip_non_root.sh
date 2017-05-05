#!/bin/sh
wget https://www.python.org/ftp/python/2.7.13/Python-2.7.13.tgz
tar -xzf Python-2.7.13.tgz
cd Python-2.7.13
mkdir -p $HOME/bin
./configure --prefix="$HOME"
make
make install
wget https://bootstrap.pypa.io/get-pip.py
$HOME/bin/python get-pip.py