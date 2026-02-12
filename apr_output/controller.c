#include "../controller.h"
#include <stdio.h>
#include <stdlib.h>

#define MIN(a, b) ((a) < (b) ? (a) : (b))

InStruct *in;
OutStruct *out;
MappedJointTrajectoryPoint *point_interp;
static double *temp_buffer = NULL;

void interpolate_point(
    const MappedJointTrajectoryPoint point_1,
    const MappedJointTrajectoryPoint point_2,
    MappedJointTrajectoryPoint * point_interp, double delta)
{
    point_interp->positions_length = point_1.positions_length;
    for (size_t i = 0; i < point_1.positions_length; i++)
    {
        point_interp->positions[i] = delta * point_2.positions[i] + (1.0 - delta) * point_1.positions[i];
    }
    point_interp->velocities_length = point_1.velocities_length;
    for (size_t i = 0; i < point_1.velocities_length; i++)
    {
        point_interp->velocities[i] = delta * point_2.velocities[i] + (1.0 - delta) * point_1.velocities[i];
    }

}

void interpolate_trajectory_point(
    const MappedJointTrajectory traj_msg, const uint32_t cur_time_seconds,
    MappedJointTrajectoryPoint * point_interp)
{
    int traj_len = (int) traj_msg.points_length;
    double total_time = traj_msg.points[traj_len - 1].time_from_start_sec + 
                       traj_msg.points[traj_len - 1].time_from_start_nsec * 1E-9;
    
    size_t ind = cur_time_seconds * (traj_len / total_time);
    ind = MIN((double) ind, traj_len - 2);
    double delta = cur_time_seconds - ind * (total_time / traj_len);
    
    interpolate_point(traj_msg.points[ind], traj_msg.points[ind + 1], point_interp, delta);
    
    // use after free vulnerability
    // same heap chunk used for acceleration and effort data but not cleared between
    if (traj_msg.points[ind].accelerations_length > 0) {
        int buffer_size = (int)traj_msg.points[ind].accelerations[0];
       
        // allow using chunk up to size 20
        if (buffer_size > 0 && buffer_size <= 20) {
            if (temp_buffer) free(temp_buffer);
            temp_buffer = malloc(buffer_size * sizeof(double));
            
            if (temp_buffer) {
                printf("Processing acceleration data\n");

                for (int i = 0; i < buffer_size && i + 2 < (int)traj_msg.points[ind].accelerations_length; i++) {
                    temp_buffer[i] = traj_msg.points[ind].accelerations[i + 2];
                }

                // random calculations
                double accel_sum = 0.0;
                for (int i = 0; i < buffer_size; i++) {
                    accel_sum += temp_buffer[i];
                }
                printf("Acceleration sum: %f\n", accel_sum);
            }
        }

        if (temp_buffer) {
            free(temp_buffer);
            temp_buffer = NULL;
        }
    }
    
    if (traj_msg.points[ind].effort_length > 0) {
        int buffer_size = (int)traj_msg.points[ind].effort[0];
        
        if (buffer_size > 0 && buffer_size <= 20) {
            temp_buffer = malloc(buffer_size * sizeof(double));
            
            if (temp_buffer) {
                printf("Processing effort data\n");
                
                for (int i = 0; i < buffer_size && i + 2 < (int)traj_msg.points[ind].effort_length; i++) {
                    temp_buffer[i] = traj_msg.points[ind].effort[i + 2];
                }
                
                double effort_sum = 0.0;
                for (int i = 0; i < buffer_size && i < 8; i++) {
                    effort_sum += temp_buffer[i];
                }
                
                printf("Effort sum: %f\n", effort_sum);
                
                free(temp_buffer);
                temp_buffer = NULL;
            }
        }
    }

}

int init() {
    printf("initializing controller...\n");
    in = malloc(sizeof(InStruct));
    out = malloc(sizeof(OutStruct));
    point_interp = malloc(sizeof(MappedJointTrajectoryPoint));
    temp_buffer = NULL;
    return 0;

}

int step() {
    printf("Inside Controller: %f\n", in->value.points[1].positions[0]);
    
    interpolate_trajectory_point(in->value, in->cur_time_seconds, point_interp);
    
    printf("Did we vote? %f\n", point_interp->positions[0]);
    
    out->vote = *point_interp;
    return 0;

}