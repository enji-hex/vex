#!/bin/sh

# $1 is a dir/file path
footprint(){
    find "$1" -name "*.py" -exec grep -vE '^\s*(#|$)' {} + | wc -l
}

vex_shell=$(footprint "./src/vex_shell/")
vex_cli=$(footprint "./src/vex_cli/")

echo "---------------------"
echo "Module    LOC"
echo "VEX_SHELL $vex_shell"
echo "VEX_CLI   $vex_cli"

total=$((vex_shell + vex_cli))
echo "TOTAL     $total"
echo "---------------------"
