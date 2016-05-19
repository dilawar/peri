from collections import OrderedDict

from peri.util import listify, delistify

class ParameterGroup(object):
    category = 'param'

    def __init__(self, params=None, values=None):
        """
        Set up a parameter group, which is essentially an OrderedDict of param
        -> values. However, it is generalized so that this structure is not
        strictly enforced for all ParameterGroup subclasses.
        """
        if params is not None and values is not None:
            self._params = OrderedDict()
            for p,v in zip(params, values):
                self._params[p] = v
        elif params is not None and values is None:
            self._params = params
        else:
            self._params = OrderedDict()

    def update(self, params, values):
        """
        Update the a single (param, value) combination, or a list or tuple of
        params and corresponding values for the object.
        """
        self.set_values(params, values)

    def get_values(self, params):
        """ Get the value of a list or single parameter """
        values = delistify([self._params[p] for p in listify(params)])
        return values

    def set_values(self, params, values):
        """
        Directly set a single (param, value) combination, or a list or tuple of
        params and corresponding values for the object.
        """
        for p, v in zip(listify(params), listify(values)):
            self._params[p] = v

    @property
    def params(self):
        return self._params.keys()

    @property
    def values(self):
        return self._params.values()


class Component(ParameterGroup):
    # TODO make all components serializable via _getinitargs_
    def __init__(self, params, values):
        super(Component, self).__init__(params, values)

    def get_support_size(self, params, values):
        """
        This method returns a `peri.util.Tile` object defining the region of
        a field that has to be modified by the update of (params, values).

        Parameters:
        -----------
        params : single param, list of params
            A single parameter or list of parameters to be updated

        values : single value, list of values
            The values corresponding to the params

        Returns:
        --------
        tile : `peri.util.Tile`
            A tile corresponding to the image region
        """
        raise NotImplementedError("get_support_size required for components")

    def get_padding_size(self, params, values):
        raise NotImplementedError("get_padding_size required for components")

    def get_field(self):
        raise NotImplementedError("get_field required for components")

    def set_tile(self, tile):
        raise NotImplementedError("set_tile required for components")

