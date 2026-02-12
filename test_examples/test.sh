#!/bin/bash
test_id=$1
here_dir=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )

test_dir="$here_dir/test"
executable="/experiment/source/controller"

case $test_id in
    p1|p2|p3|p4|p5|p6|p7|p8|p9|p10|n1|n2)

        $executable &
        pid=$!

        oracle=$test_dir/$test_id

        python3 check_distance.py $oracle
        exit_code=$?

        kill $pid

        if [ $exit_code -eq 1 ]; then
            exit 1
        fi


        # for i in {1..10}
        # do
        #     echo STARTING A NEW ITTERATION
        #     # give the controller the next state
        #     # cp is not atomic but mv is
        #     mv ./_state ./old_state

        #     cp $test_dir/$test_id/t$i ./tmp_state
        #     mv ./tmp_state ./_state

        #     # give the controller time to run
        #     sleep 1

        #     oracle=$test_dir/$test_id/output.t$i

        #     python3 check_distance.py $oracle
        #     exit_code=$?

        #     if [ $exit_code -eq 1 ]; then
        #         exit 1
        #     fi

        #     # exit $exit_code
        #     # ;;
        # done

        # If we got here then they all must have passed
        exit 0
        ;;

    *)
        exit 1
        ;;
esac