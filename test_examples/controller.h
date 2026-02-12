#ifndef CONTROLLER_H
#define CONTROLLER_H

// ROS2 Stuff

// #include "ros2_control_demo_example_7/r6bot_controller.hpp"

#include <stddef.h>
#include <stdint.h>
// #include <algorithm>
// #include <memory>
// #include <string>
// #include <vector>

// #include "rclcpp/qos.hpp"
// #include "rclcpp/time.hpp"
// #include "rclcpp_lifecycle/node_interfaces/lifecycle_node_interface.hpp"
// #include "rclcpp_lifecycle/state.hpp"

typedef struct {
    size_t positions_length;
    double positions[100]; // Assuming a maximum of 100 positions

    size_t velocities_length;
    double velocities[100]; // Assuming a maximum of 100 velocities

    size_t accelerations_length;
    double accelerations[100]; // Assuming a maximum of 100 accelerations

    size_t effort_length;
    double effort[100]; // Assuming a maximum of 100 effort values

    int32_t time_from_start_sec; // seconds part of the duration
    uint32_t time_from_start_nsec; // nanoseconds part of the duration
} MappedJointTrajectoryPoint;

typedef struct {
    size_t joint_names_length;
    char joint_names[10][256]; // Assuming a maximum of 10 joint names, each with a maximum length of 256

    size_t points_length;
    MappedJointTrajectoryPoint points[256]; // Assuming a maximum of 100 points
} MappedJointTrajectory;

typedef struct
{
    MappedJointTrajectory value;
    uint32_t cur_time_seconds;
} InStruct;

typedef struct
{
    MappedJointTrajectoryPoint vote;
} OutStruct;





extern InStruct *in;
extern OutStruct *out;


int init();
int step();


#endif