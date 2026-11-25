#!/bin/bash
cd "$(dirname "$0")"
./start.sh
open "http://127.0.0.1:8000/"
