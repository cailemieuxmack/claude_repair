#!/bin/bash

# Execute the command passed to the container
bash -c "$@" &

# Wait for the files to be created and change their permissions
while true; do
  if [ "$(ls -A /tmp)" ]; then
    find /tmp -type f -exec chmod +w {} \;
    break
  fi
  sleep 1
done

# Wait for your application to finish
wait