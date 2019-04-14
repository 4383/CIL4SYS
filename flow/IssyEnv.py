import numpy as np

from gym.spaces.tuple_space import Tuple
from gym.spaces.box import Box

from flow.envs import Env

class IssyEnv(Env):
    @property
    def action_space(self):
        return Box(low=0, high=1, shape=(self.k.traffic_light.num_traffic_lights,),
                dtype=np.float32)

    @property
    def observation_space(self):
        return Box(
            low=0,
            high=float("inf"),
            shape=(2*self.scenario.vehicles.num_vehicles,),
        )

    def get_state(self, **kwargs):
        # the get_ids() method is used to get the names of all vehicles in the network
        ids = self.k.vehicle.get_ids()[:20]

        # we use the get_absolute_position method to get the positions of all vehicles
        pos = [self.k.vehicle.get_x_by_id(veh_id) for veh_id in ids]

        # we use the get_speed method to get the velocities of all vehicles
        vel = [self.k.vehicle.get_speed(veh_id) for veh_id in ids]

        tl = [self.k.traffic_light.get_state(t) for t in self.k.traffic_light.get_ids()]
        # the speeds and positions are concatenated to produce the state
        return np.concatenate((pos, vel))

    def _invert_tl_state(self, id):
        old_state = self.k.traffic_light.get_state(id)
        state = old_state.replace("g", "G")
        state = state.replace("y", "r")
        state = state.replace("G", "tmp")
        state = state.replace("r", "G")
        state = state.replace("tmp", "r")
        return state

    def _apply_rl_actions(self, rl_actions):
        # the names of all autonomous (RL) vehicles in the network
        rl_ids = self.k.traffic_light.get_ids()
        actions = np.round(rl_actions)

        # use the base environment method to convert actions into accelerations for the rl vehicles
        for id, a in zip(rl_ids, actions):
            if a:
                state = self._invert_tl_state(id)
                self.k.traffic_light.set_state(id, state)

    def compute_reward(self, rl_actions, **kwargs):
        # the get_ids() method is used to get the names of all vehicles in the network
        ids = self.k.vehicle.get_ids()

        # we next get a list of the speeds of all vehicles in the network
        speeds = self.k.vehicle.get_speed(ids)

        # finally, we return the average of all these speeds as the reward
        return np.mean(speeds)