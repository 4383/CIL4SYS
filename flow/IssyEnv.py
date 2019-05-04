import itertools
import numpy as np

from gym.spaces.box import Box

from flow.envs import Env

from Rewards import Rewards
from helpers import flatten, pad_list, invert_tl_state


class IssyEnvAbstract(Env):
    """Abstract class to inherit from. It provides helpers
    used accross models such as a traffic light state inversion method

    Required from env_params:

    * beta: (int) number of vehicles the agent can observe
    * action_spec: (dict<str,[str]>) allowed states for each traffic
        light ID.


    States
        To be defined in child class.

    Actions
        The action space consist of a list of float variables ranging from 0-1
        specifying whether a traffic light is supposed to switch or not.

    Rewards
        To be defined in child class.

    Termination
        A rollout is terminated once the time horizon is reached.
    """

    def __init__(self, env_params, sim_params, scenario, simulator='traci'):
        super().__init__(env_params, sim_params, scenario, simulator)
        beta = env_params.get_additional_param("beta")
        self.action_spec = env_params.get_additional_param("action_spec")
        self.model_params = dict(beta=beta, )
        self.rewards = Rewards(self.k)

    def map_action_to_tl_states(self, rl_actions):
        """Maps an rl_action list to new traffic light states based on
        `action_spec`

        Parameters
        ---------
        rl_actions: [float] list of action probabilities of cardinality
            `self.get_num_actions()`
        """
        all_actions = list(itertools.product(*list(self.action_spec.values())))
        return all_actions[np.argmax(rl_actions)]

    def get_num_traffic_lights(self):
        """Counts the number of traffic lights by summing
        the state string length for each intersection.

        Returns
        -------
        Number of traffic lights (int)"""
        count = 0
        for k in self.action_spec.keys():
            count += len(self.action_spec[k][0])
        return count

    def get_num_actions(self):
        """Calculates the number of possible actions by counting the
        traffic light states based on `self.action_spec`. It counts
        the cardinality of the cartesian product of all traffic light
        states.

        Returns
        -------
        Number of actions (int)
        """
        count = 1
        for k in self.action_spec.keys():
            count *= len(self.action_spec[k])
        return count

    @property
    def action_space(self):
        """Vector of floats from 0-1 indicating traffic light states."""
        return Box(low=0,
                   high=1,
                   shape=(self.get_num_actions(), ),
                   dtype=np.float32)

    def encode_tl_state(self, id):
        """Encodes traffic light state.
        Yellow and red states are considered off and all other states
        are considered on.

        "rryGyggrrGGrg" => [0, 0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1]

        See: https://sumo.dlr.de/wiki/Simulation/Traffic_Lights

        Parameters
        ----------
        id: str
            ID of traffic light to encode state.

        Returns
        ----------
        encoded_state: [bool]
            Encoded light state
        """
        state = list(self.k.traffic_light.get_state(id))
        red_lights = list("ry")
        return [0 if s in red_lights else 1 for s in state]

    def get_controlled_tl_ids(self):
        """Returns the list of RL controlled traffic lights."""
        return [
            id for id in self.k.traffic_light.get_ids()
            if id in self.action_spec.keys()
        ]

    def get_free_tl_ids(self):
        """Returns the list of uncontrollable traffic lights."""
        return [
            id for id in self.k.traffic_light.get_ids()
            if id not in self.action_spec.keys()
        ]

    def _apply_rl_actions(self, rl_actions):
        """Converts probabilities of choosing configuration for states of
        traffic lights on the map. All traffic lights for which IDs are not
        keys of `self.action_spec` are updated to all green light states.

        Parameters
        ----------
        rl_actions: [float]
            Individual probabilities of choosing a particular traffic
            light state configuration for controllable traffic lights on
            the map.
        """
        # Upadate controllable traffic lights
        new_tl_states = self.map_action_to_tl_states(rl_actions)
        for counter, tl_id in enumerate(self.action_spec.keys()):
            self.k.traffic_light.set_state(tl_id, new_tl_states[counter])

        # Set all other traffic lights to green
        free_tl_ids = self.get_free_tl_ids()
        for tl_id in free_tl_ids:
            old_state = self.k.traffic_light.get_state(tl_id)
            new_state = "G" * len(old_state)
            self.k.traffic_light.set_state(tl_id, new_state)

    def additional_command(self):
        """Used to insert vehicles that are on the exit edge and place them
        back on their entrance edge. Gets executed at each time step.

        See parent class for more information."""
        for veh_id in self.k.vehicle.get_ids():
            self._reroute_if_final_edge(veh_id)

    def get_observable_veh_ids(self):
        """Get the ids of all the vehicles observable by the model.

        Returns
        -------
        A list of vehicle ids (str)
        """
        return [id for id in self.k.vehicle.get_ids() if "human" in id]

    def _reroute_if_final_edge(self, veh_id):
        """Checks if an edge is the final edge. If it is spawn a new
        vehicle on a random edge and remove the old one."""

        # no need to reroute inflows
        if "flow" in veh_id:
            return

        # don't reroute if vehicle is not on route final edge
        current_edge = self.k.vehicle.get_edge(veh_id)
        final_edge = self.k.vehicle.get_route(veh_id)[-1]
        if current_edge != final_edge:
            return

        type_id = self.k.vehicle.get_type(veh_id)

        # remove the vehicle
        self.k.vehicle.remove(veh_id)
        # reintroduce it at the start of the network
        random_route = self.scenario.get_random_route()
        self.k.vehicle.add(veh_id=veh_id,
                           edge=random_route,
                           type_id=str(type_id),
                           lane=str(0),
                           pos="0",
                           speed="max")


class IssyEnv1(IssyEnvAbstract):
    """First environment used to train traffic lights to regulate traffic flow
    for the Issy les Moulineaux district of study.

    Required from env_params: See parent class

    States
        An observation is the set of positions and speeds of beta observed
        vehicles

    Actions
        See parent class

    Rewards
        The reward is the average speed of all vehicles present on the mesh.

    Termination
        See parent class
    """

    @property
    def observation_space(self):
        """ In this model, we only observe positions and speeds of
        the beta observable vehicles in cartesian coordinates,
        along with their absolute speed and CO2 emission.

        (See parent class for more information)"""

        return Box(
            low=0,
            high=float("inf"),
            shape=(5 * self.scenario.vehicles.num_vehicles +
                   self.get_num_traffic_lights(), ),
        )

    def get_state(self, **kwargs):
        """ We request positions, orientations, speeds, and emissions
        of observable vehicles.

        (See parent class for more information)"""
        # We select beta observable vehicles and exclude inflows
        ids = self.get_observable_veh_ids()

        vel = [self.k.vehicle.get_speed(veh_id) for veh_id in ids]
        orientation = [
            self.k.vehicle.get_orientation(veh_id) for veh_id in ids
        ]
        emission = [
            self.k.vehicle.kernel_api.vehicle.getCO2Emission(id) for id in ids
        ]

        tl = np.concatenate([
            self.encode_tl_state(id) for id in self.k.traffic_light.get_ids()
            if id in self.action_spec.keys()
        ])

        # We pad the state in case a vehicle is being respawned to prevent
        # dimension related exceptions
        vel = pad_list(vel, self.model_params["beta"], 0.)
        orientation = pad_list(orientation, self.model_params["beta"],
                               [0., 0., 0.])
        emission = pad_list(emission, self.model_params["beta"], 0.)

        return np.concatenate((flatten(orientation), vel, emission, tl))

    def compute_reward(self, rl_actions, **kwargs):
        """ The reward in this simple model is simply the mean velocity
        of all simulated vehicles present on the mesh devided by the
        mean CO2 emission.

        (See parent class for more information)"""

        return self.rewards.mean_speed() / self.rewards.mean_emission()
