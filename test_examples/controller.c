#include "../controller.h"
#include <stdio.h>
#include <stdlib.h>

#define MIN(a, b) ((a) < (b) ? (a) : (b))


// InStruct in;
// OutStruct out;

InStruct *in;
OutStruct *out;

MappedJointTrajectoryPoint *point_interp;



void interpolate_point(
    const MappedJointTrajectoryPoint point_1,
    const MappedJointTrajectoryPoint point_2,
    MappedJointTrajectoryPoint * point_interp, double delta)
  {
    for (size_t i = 0; i < point_1.positions_length; i++)
    {
      point_interp->positions[i] = delta * point_2.positions[i] + (1.0 - delta) * point_1.positions[i];
    }
    for (size_t i = 0; i < point_1.positions_length; i++)
    {
      point_interp->velocities[i] =
        delta * point_2.velocities[i] + (1.0 - delta) * point_1.velocities[i];
    }
  
  }
  
  void interpolate_trajectory_point(
    const MappedJointTrajectory traj_msg, const uint32_t cur_time_seconds,
    MappedJointTrajectoryPoint * point_interp)
  {
    int traj_len = (int) traj_msg.points_length;
    //auto last_time = traj_msg.points[traj_len - 1].time_from_start;
    double total_time = traj_msg.points[traj_len - 1].time_from_start_sec + traj_msg.points[traj_len - 1].time_from_start_nsec * 1E-9;
    //double total_time = last_time.sec + last_time.nanosec * 1E-9;
  
    size_t ind = cur_time_seconds * (traj_len / total_time);
    ind = MIN( (double) ind, traj_len - 2);
    double delta = (double)(int)(cur_time_seconds - ind * (total_time / traj_len));
    interpolate_point(traj_msg.points[ind], traj_msg.points[ind + 1], point_interp, delta);
  
  }


int init() {
    printf("initializing controller...\n");
    in = malloc(sizeof(InStruct));
    out = malloc(sizeof(OutStruct));
    point_interp = malloc(sizeof(MappedJointTrajectoryPoint));

}


int step() {
    // double msg = in[0];
    printf("Inside Controller: %f\n", in->value.points[1].positions[0]);
    // out[0] = msg + 1;
    // const trajectory_msgs::msg::JointTrajectory & traj_msg = in.traj_msg;
    // const rclcpp::Duration & cur_time = in.time - in.start_time;

    interpolate_trajectory_point(in->value, in->cur_time_seconds, point_interp);

    printf("Did we vote? %f\n", point_interp->positions[0]);

    out->vote = *point_interp;

}
