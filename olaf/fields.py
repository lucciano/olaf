import bson
import datetime

class NoPersist:
    """ Allows performing field assignments
    without persisting changes into database,
    useful for performing validations.
    """

    def __init__(self, instance):
        self.instance = instance

    def __enter__(self):
        self.instance._implicit_save = False

    def __exit__(self, type, value, traceback):
        self.instance._implicit_save = True


class BaseField:
    """ Base field with default initializations
    and validations. All other fields should extend
    this class.
    """

    def __init__(self, *args, **kwargs):
        self.attr = None    # Silence Linters
        # Get basic attributes
        self._required = kwargs.get("required", False)
        self._unique = kwargs.get("unique", False)
        # Unique fields are always required
        if self._unique:
            self._required = True
        # Keep _default undeclared if not specified
        if "default" in kwargs:
            self._default = kwargs["default"]
        # Excluded fields won't be returned on read()
        self._exclude = kwargs.get("exclude", False)
        # Custom setter function allows overriding default behaviour
        if "setter" in kwargs:
            self._setter = kwargs["setter"]
        # For now set string for keyword args
        self._string = kwargs.get("string", self.attr)

    def __set__(self, instance, value):
        if value is None and self._required:
            raise ValueError("Field {} is required".format(self.attr))
        if hasattr(self, "_setter"):
            # Get value from custom setter
            setter = getattr(instance, self._setter)
            value = setter(value)
        instance._buffer[self.attr] = value
        if getattr(instance, "_implicit_save", True):
            instance._save()
        return None

    def __get__(self, instance, owner):
        if instance is None:
            return self
        else:
            count = instance.count()
            if count == 1:
                attr = self.attr
                instance._cursor.rewind()
                item = instance._cursor.next()
            elif count == 0:
                return
            else:
                # Call ensure_one to raise ValueError
                instance.ensure_one()
            return item.get(attr)


class Identifier(BaseField):
    """ Field Class for storing Document ObjectIDs
    """

    def __set__(self, instance, value):
        if not isinstance(value, bson.ObjectId):
            try:
                value = bson.ObjectId(value)
            except TypeError:
                raise TypeError(
                    "Cannot convert value of type {} to ObjectId".format(type(value).__name__))
        instance._buffer[self.attr] = value


class Char(BaseField):
    """ Field Class for storing strings
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        max_length = kwargs.get("max_length", 255)
        if not isinstance(max_length, int):
            raise TypeError("Parameter max_length must be integer, got {} instead".format(
                max_length.__class__.__name__))
        self._max_length = max_length

    def __set__(self, instance, value):
        if value is not None:
            if not isinstance(value, str):
                try:
                    value = str(value)
                except TypeError:
                    raise TypeError(
                        "Cannot convert value of type {} to string".format(type(value).__name__))
            if len(value) > self._max_length:
                raise ValueError("Value {} exceeds maximum length of {}".format(
                    value, self._max_length))
        super().__set__(instance, value)


class Integer(BaseField):
    """ Field Class for storing integer numbers
    """

    def __set__(self, instance, value):
        if value is not None:
            if not isinstance(value, int):
                try:
                    value = int(value)
                except ValueError:
                    raise ValueError(
                        "Cannot convert '{}' to integer".format(str(value)))
        super().__set__(instance, value)


class Boolean(BaseField):
    """ Field Class for storing boolean values
    """

    def __set__(self, instance, value):
        if value is not None:
            if not isinstance(value, bool):
                if value in ["false", "0", 0]:
                    value = False
                elif value in ["true", "1", 1]:
                    value = True
                else:
                    raise ValueError(
                        "Cannot convert '{}' to boolean".format(str(value)))
        super().__set__(instance, value)


class DateTime(BaseField):
    """ Field Class for storing datetime values
    """
    def __set__(self, instance, value):
        if value is not None:
            if not isinstance(value, datetime.datetime):
                try:
                    value = datetime.datetime.fromisoformat(value)
                except ValueError:
                    raise ValueError(
                        "Cannot convert '{}' to datetime".format(str(value)))
        super().__set__(instance, value)

class RelationalField(BaseField):
    """ Provides a set of common utilities
    for relational fields.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        comodel_name = (args[0:1] or (None,))[0]
        if comodel_name is None:
            raise ValueError("comodel_name not specified")
        self._comodel_name = comodel_name
        self._represent = kwargs.get("represent", "name")

    def _get_comodel(self, instance):
        if self._comodel_name is None:
            raise ValueError("comodel_name not specified")
        if self._comodel_name not in instance.env.registry:
            raise ValueError("comodel_name '{}' not found in registry".format(self._comodel_name))
        return instance.env[self._comodel_name]

    def _ensure_oid(self, value):
        """ Ensure the provided value is an ObjectId or a compatible string """
        if not isinstance(value, bson.ObjectId):
            from olaf.models import Model  # FIXME: Importing this here to avoid circular import
            if issubclass(value.__class__, Model):
                # The provided value is a DocSet
                value.ensure_one()
                return value._id
            try:
                value = bson.ObjectId(value)
            except TypeError:
                raise TypeError(
                    "Cannot convert value of type {} to ObjectId".format(type(value).__name__))
            except bson.errors.InvalidId:
                raise TypeError(
                    "The supplied value '{}' is not a valid ObjectId".format(str(value)))
        return value

    def _is_comodel_oid(self, oid, instance):
        """ Ensure the provided oid exists in the co-model """
        item = instance.env[self._comodel_name].browse(oid)
        if item.count() == 0:
            raise ValueError(
                "The supplied ObjectId does not exist in the target model")
        return item


class Many2one(RelationalField):
    """ Field Class for storing a representation of
    a record from a different collection or the same one
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ondelete = kwargs.get("ondelete", "SET NULL")

    def __get__(self, instance, owner):
        """ Returns a DocSet containing a single document
        associated to the corresponding comodel and the
        requested ObjectId
        """
        value = super().__get__(instance, owner)
        if value is None or not isinstance(value, bson.ObjectId):
            return value
        cmod = self._get_comodel(instance)
        return cmod.browse(value)

    def __set__(self, instance, value):
        if value is not None:
            _ = self._get_comodel(instance)
            value = self._ensure_oid(value)
            self._is_comodel_oid(value, instance)
        super().__set__(instance, value)


class One2many(RelationalField):
    """ Field Class for storing a list
    of references to a given model
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inversed_by = (args[1:2] or (None,))[0] or kwargs["inversed_by"]
        if inversed_by is None:
            raise ValueError("inversed_by not specified")
        self._inversed_by = inversed_by

    def __get__(self, instance, owner):
        if instance is None:
            return self
        instance.ensure_one()
        cmod = self._get_comodel(instance)
        if not hasattr(cmod, self._inversed_by):
            raise AttributeError(
                "Inverse relation '{}' not found in model '{}'".format(
                    self._inversed_by, cmod._name))
        return cmod.search({self._inversed_by: instance._id})

    def __set__(self, instance, list_tuples):
        """ Sets the value of a One2many relationship

        Since x2many fields are virtual, and in order to allow a 
        create() or write() operation involving this type of field without
        the need of calling any special methods, assignment of values must 
        be done through the following special syntax, which is a list of
        tuples that wil be secuentially executed.

        Unlike Odoo, which uses tuples identified by a number, Olaf expects
        a much more intuitive string in exchange.
        
        Odoo Syntax         | Olaf Syntax         | Description
        -----------------------------------------------------------------------------------------------------
        (0, 0,  { values }) | ('create', {v})     | Link to a new record that needs to be created with the given values dictionary
        (1, ID, { values }) | ('write', OID, {v}) | Update the linked record with id = ID (write *values* on it)
        (2, ID, 0)          | ('purge', OID)      | Remove and delete the linked record with id = ID (calls unlink on ID, that will delete the object completely, and the link to it as well)
        (3, ID, 0)          | ('remove', OID)     | Cut the link to the linked record with id = ID (delete the relationship between the two objects but does not delete the target object itself)
        (4, ID, 0)          | ('add', OID)        | Link to existing record with id = ID (adds a relationship)
        (5, 0, 0)           | ('clear')           | Unlink all (like using (3,ID) for all linked records)
        (6, 0, [IDs])       | ('replace', [OIDs]) | Replace the list of linked IDs (like using (5) then (4,ID) for each ID in the list of IDs)
        """
        save = getattr(instance, "_implicit_save", True)
        for value in list_tuples:
            if value is None:
                # Treat None assignment as clear
                value = ("clear",)

            if not isinstance(value, tuple):
                if value == 'clear':
                    # Fix wrong singleton tuple
                    value = ('clear',)
                else:
                    raise TypeError(
                        "One2many field assignments must be done through tuple-list syntax. "
                        "Check the documentation for further details.")

            if len(value) == 0:
                raise ValueError("Empty tuple supplied for x2many assignment")

            if value[0] == "create":
                # Create a new record in the co-model
                # and assign its 'inversed_by' field to this record.
                if len(value) != 2:
                    raise ValueError(
                        "Invalid tuple length for x2many create assignment")
                if not isinstance(value[1], dict):
                    raise TypeError(
                        "Tuple argument #2 must be dict, got {} instead".format(
                            value[1].__class__.__name__))
                if save:
                    values = value[1]
                    values[self._inversed_by] = instance._id
                    instance.env[self._comodel_name].create(values)
            elif value[0] == "write":
                # Update an existing record in the co-model
                # by assigning its 'inversed_by' field to this record.
                if len(value) != 3:
                    raise ValueError(
                        "Invalid tuple length for x2many write assignment")
                oid = self._ensure_oid(value[1])
                item = self._is_comodel_oid(oid, instance)
                if not isinstance(value[2], dict):
                    raise TypeError(
                        "Tuple argument #2 must be dict, got {} instead".format(
                            value[2].__class__.__name__))
                if save:
                    values = value[2]
                    item.write(values)
            elif value[0] == "purge":
                # Delete the co-model record
                if len(value) != 2:
                    raise ValueError(
                        "Invalid tuple length for x2many purge assignment")
                oid = self._ensure_oid(value[1])
                item = self._is_comodel_oid(oid, instance)
                if save:
                    item.unlink()
            elif value[0] == "remove":
                # Remove the reference to this record by clearing
                # the 'inversed_by' field in the co-model record
                if len(value) != 2:
                    raise ValueError(
                        "Invalid tuple length for x2many remove assignment")
                oid = self._ensure_oid(value[1])
                item = self._is_comodel_oid(oid, instance)
                if save:
                    item.write({self._inversed_by: None})
            elif value[0] == "add":
                # Add a reference to this record by setting
                # the 'inversed_by' field in the co-model record
                if len(value) != 2:
                    raise ValueError(
                        "Invalid tuple length for x2many add assignment")
                oid = self._ensure_oid(value[1])
                item = self._is_comodel_oid(oid, instance)
                if save:
                    item.write({self._inversed_by: instance._id})
            elif value[0] == "clear":
                # Set all the references to this record to None
                if len(value) != 1:
                    raise ValueError(
                        "Invalid tuple length for x2many clear assignment")
                if save:
                    instance.env[self._comodel_name].search(
                        {self._inversed_by: instance._id}).write(
                            {self._inversed_by: None})
            elif value[0] == "replace":
                # Perform a clear and then add each element of the supplied list
                if len(value) != 2:
                    raise ValueError(
                        "Invalid tuple length for x2many clear assignment")
                if not isinstance(value[1], list):
                    raise TypeError(
                        "Tuple argument #2 must be list, got {} instead".format(
                            value[1].__class__.__name__))
                if save:
                    comodel = self._get_comodel(instance)
                    comodel.search({self._inversed_by: instance._id}
                                ).write({self._inversed_by: None})
                    comodel.browse(value[1]).write({self._inversed_by: instance._id})
            else:
                raise ValueError(
                    "Tuple #1 argument must be 'create', 'write', 'purge', 'remove', 'add', 'clear' or 'replace'")
        if not save:
            instance._buffer[self.attr] = list_tuples


class Many2many(RelationalField):
    """ A many2many relationship works by creating an intermediate
    model with two Many2one fields, each one pointing to one of the
    involved models, resulting in a One2many field in  ends.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._relation  = (args[1:2] or (None,))[0] or kwargs["relation"]
        self._field_a   = (args[2:3] or (None,))[0] or kwargs["field_a"]
        self._field_b   = (args[3:4] or (None,))[0] or kwargs["field_b"]

    def _ensure_intermediate_model(self, instance):
        """ Declare intermediate model exists 
        """

        if self._relation not in instance.env.registry.__models__:
            # Import Model and ModelMeta
            from olaf.models import Model, ModelMeta
            # Create fields
            rel_fld_a = Many2one(instance._name, required=True)
            rel_fld_b = Many2one(self._comodel_name, required=True)
            # Extract __dict__ (all Model's attributes, methods and descriptors)
            model_dict = dict(Model.__dict__)
            # Inject name and fields
            model_dict["_name"] = self._relation
            model_dict[self._field_a] = rel_fld_a
            model_dict[self._field_b] = rel_fld_b
            model_dict["_compound_indexes"] = [
                (self._field_a, self._field_b)]
            # Create metaclass
            mod = ModelMeta("Model", (), model_dict)
            instance.env.registry.add(mod)


    def __get__(self, instance, owner):
        """ Search for relationships in the intermediate model
        containing references to the instance id, and with these
        results, browse the comodel for matches.
        """
        if instance is None:
            return self
        instance.ensure_one()
        self._ensure_intermediate_model(instance)
        # Perform search and browse
        rels = instance.env[self._relation].search({self._field_a: instance._id})
        return instance.env[self._comodel_name].browse(
            [getattr(rel, self._field_b)._id for rel in rels])

    def __set__(self, instance, list_tuples):
        """ A patched version of the O2M __set__ descriptor.
        """
        save = getattr(instance, "_implicit_save", True)
        for value in list_tuples:
            if value is None:
                # Treat None assignment as clear
                value = ("clear",)

            if not isinstance(value, tuple):
                if value == 'clear':
                    # Fix wrong singleton tuple
                    value = ('clear',)
                else:
                    raise TypeError(
                        "Many2many field assignments must be done through tuple-list syntax. "
                        "Check the documentation for further details.")

            # Create intermediate model if not present
            self._ensure_intermediate_model(instance)

            if value[0] == "create":
                # Create a new record in the co-model and add virtual relationship
                if len(value) != 2:
                    raise ValueError(
                        "Invalid tuple length for x2many create assignment")
                if not isinstance(value[1], dict):
                    raise TypeError(
                        "Tuple argument #2 must be dict, got {} instead".format(
                            value[1].__class__.__name__))
                
                values = value[1]
                if save:
                    rec = instance.env[self._comodel_name].create(values)
                    instance.env[self._relation].create(
                        {self._field_a: instance._id, self._field_b: rec._id})
            elif value[0] == "write":
                # Update an existing record in the co-model
                # by assigning its 'inversed_by' field to this record.
                if len(value) != 3:
                    raise ValueError(
                        "Invalid tuple length for x2many write assignment")
                oid = self._ensure_oid(value[1])
                item = self._is_comodel_oid(oid, instance)
                if not isinstance(value[2], dict):
                    raise TypeError(
                        "Tuple argument #2 must be dict, got {} instead".format(
                            value[2].__class__.__name__))
                if save:
                    values = value[2]
                    item.write(values)
            elif value[0] == "purge":
                # Delete the co-model record
                if len(value) != 2:
                    raise ValueError(
                        "Invalid tuple length for x2many purge assignment")
                oid = self._ensure_oid(value[1])
                item = self._is_comodel_oid(oid, instance)
                if save:
                    item.unlink()
                    instance.env[self._relation].search({self._field_b: oid}).unlink()
            elif value[0] == "remove":
                # Remove the reference to this record by clearing
                # the 'inversed_by' field in the co-model record
                if len(value) != 2:
                    raise ValueError(
                        "Invalid tuple length for x2many remove assignment")
                oid = self._ensure_oid(value[1])
                item = self._is_comodel_oid(oid, instance)
                if save:
                    instance.env[self._relation].search({self._field_b: oid}).unlink()
            elif value[0] == "add":
                # Add a reference to this record by setting
                # the 'inversed_by' field in the co-model record
                if len(value) != 2:
                    raise ValueError(
                        "Invalid tuple length for x2many add assignment")
                oid = self._ensure_oid(value[1])
                item = self._is_comodel_oid(oid, instance)
                if save:
                    instance.env[self._relation].create(
                        {self._field_a: instance._id, self._field_b: item._id})
            elif value[0] == "clear":
                # Set all the references to this record to None
                if len(value) != 1:
                    raise ValueError(
                        "Invalid tuple length for x2many clear assignment")
                if save:
                    instance.env[self._relation].search({self._field_a: instance._id}).unlink()
            elif value[0] == "replace":
                # Perform a clear and then add each element of the supplied list
                if len(value) != 2:
                    raise ValueError(
                        "Invalid tuple length for x2many clear assignment")
                if not isinstance(value[1], list):
                    raise TypeError(
                        "Tuple argument #2 must be list, got {} instead".format(
                            value[1].__class__.__name__))
                if save:
                    instance.env[self._relation].search({self._field_a: instance._id}).unlink()
                    for oid in value[1]:
                        oid = self._ensure_oid(oid)
                        _ = self._is_comodel_oid(oid, instance)
                        instance.env[self._relation].create(
                            {self._field_a: instance._id, self._field_b: oid})
            else:
                raise ValueError(
                    "Tuple #1 argument must be 'create', 'write', 'purge', 'remove', 'add', 'clear' or 'replace'")
        if not save:                    
            instance._buffer[self.attr] = list_tuples