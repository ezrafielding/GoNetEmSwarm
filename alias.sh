PREFIX='cd ~/Documents/GoNetEmSwarm/ && sudo ./run_test.sh'

cmd_alias() {
    alias start=$PREFIX' start'
    alias status=$PREFIX' status'
    alias clean=$PREFIX' clean'
    alias stop=$PREFIX' stop'
    alias check=$PREFIX' check'
    alias gndstart=$PREFIX' gndstart'
    alias fullstart=$PREFIX' fullstart'
    alias server='cd ~/Documents/GoNetEmSwarm/ && sudo gonetem-server -conf-file ./config.yaml'
}

cmd_alias
