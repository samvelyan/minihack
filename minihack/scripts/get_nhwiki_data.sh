# Copyright (c) Facebook, Inc. and its affiliates.

DATA_DIR=$(python -c 'from importlib_resources import files; print(files("nle").joinpath("minihack").joinpath("dat"), end="")')

wget https://www.dropbox.com/s/6qbfmsr3l89sip0/nethackwikidata.json

cmd="mv nethackwikidata.json $DATA_DIR"
echo $cmd
$cmd
