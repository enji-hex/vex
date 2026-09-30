#!/bin/sh

vex_shell=$(wc -l $(find -path './src/vex_shell/*.py' ) | tail -1 | grep -Po '\d+')
vex_cli=$(wc -l $(find -path './src/vex_cli/*.py' ) | tail -1  | grep -Po '\d+')

echo "---------------------"
echo "VEX_SHELL $vex_shell"
echo "VEX_CLI   $vex_cli"

total=$((vex_shell + vex_cli))
echo "TOTAL     $total"
echo "---------------------"
