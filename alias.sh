PREFIX='cd ~/Documents/GoNetEmSwarm/ && sudo ./run_test.sh'

cmd_alias() {
    alias start=$PREFIX' start'
    alias status=$PREFIX' status'
    alias clean=$PREFIX' clean'
    alias stop=$PREFIX' stop'
    alias check=$PREFIX' check'
}

cmd_alias
