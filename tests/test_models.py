import pytest
import bson
from bson import ObjectId
from olaf import db, registry, fields, models
from olaf.tools import initialize
from olaf.models import Model, DeletionConstraintError
from olaf.tools.environ import Environment

uid = ObjectId("000000000000000000000000")
env = Environment(uid)
self = registry["base.user"](env, {"_id": uid})


@registry.add
class tModel(models.Model):
    _name = "test.models.model"

    name = fields.Char()
    country = fields.Char(default="Argentina")
    age = fields.Integer()
    boolean = fields.Boolean()
    cascade_id = fields.Many2one("test.models.comodel", ondelete="CASCADE")
    restrict_id = fields.Many2one("test.models.comodel", ondelete="RESTRICT")
    setnull_id = fields.Many2one("test.models.comodel", ondelete="SET NULL")
    onetomany_ids = fields.One2many("test.models.comodel", "inverse_id")
    manytomany_ids = fields.Many2many("test.models.comodel", relation="test.model.comodel.rel", field_a="a_oid", field_b="b_oid")


@registry.add
class tCoModel(models.Model):
    _name = "test.models.comodel"

    name = fields.Char(required=True)
    inverse_id = fields.Many2one("test.models.model")


# Initialize App Engine After All Model Classes Are Declared
initialize()


def test_unicity():
    """ Make sure two instances
    are not the same instance """
    t_a = self.env["test.models.model"]
    t_b = self.env["test.models.model"]
    assert(id(t_a) != id(t_b))


def test_equality():
    """ Test DocSet comparison"""
    t_a = self.env["test.models.model"].create({"name": "Mr. Roboto"})
    t_b = self.env["test.models.model"].create({"name": "Mr. Roboto"})
    t_c = self.env["test.models.model"].search({"_id": t_a._id})
    # t_a and t_c contain the same document
    assert(t_a == t_c)
    # t_a and t_b have the same name but not same OID
    assert(t_a != t_b)


def test_model_create():
    """ Perform a basic creation of a new element.
    Make sure counters are correct and default values
    get assigned.
    """
    t = self.env["test.models.model"]
    ti = t.create({"name": "Mr. Roboto", "age": 32})
    assert(ti.count() == 1)
    assert(ti.name == "Mr. Roboto")
    assert(ti.age == 32)
    assert(ti.country == "Argentina")
    # Ensure an OID can be provided for creating a new document
    new_oid = bson.ObjectId()
    ti2 = t.create({"_id": new_oid, "name": "Mr. Colombia", "age": 33})
    assert(ti2._id == new_oid)


def test_model_create_with_2many():
    """ Create an element providing a 2many value
    """
    t = self.env["test.models.model"]
    ti = t.create({"name": "Mr. Roboto", "age": 32, "onetomany_ids": [("create", {"name": "John"})]})
    assert(ti.onetomany_ids.name == "John")


def test_model_browse():
    # Test all possible singleton browse calls
    tm1 = self.env["test.models.model"].create({"name": "Test", "age": 10})
    tm2 = self.env["test.models.model"].browse(tm1._id)
    tm3 = self.env["test.models.model"].browse([tm1._id])
    tm4 = self.env["test.models.model"].browse(str(tm1._id))
    tm5 = self.env["test.models.model"].browse([str(tm1._id)])
    assert(tm1._id == tm2._id == tm3._id == tm4._id == tm5._id)
    # Test browsing with list using OId and str
    tma = self.env["test.models.model"].create({"name": "Test_A", "age": 10})
    tmb = self.env["test.models.model"].create({"name": "Test_B", "age": 20})
    tmc = self.env["test.models.model"].browse([tma._id, str(tmb._id)])
    assert(tmc.count() == 2)
    # Browsing a non ObjectId string should fail
    with pytest.raises(bson.errors.InvalidId):
        self.env["test.models.model"].browse("123456789")
    # Browsing a list with a non ObjectId string should fail
    with pytest.raises(bson.errors.InvalidId):
        self.env["test.models.model"].browse([tma._id, "123456789"])
    # Browsing something out of a list, str or OId should fail
    with pytest.raises(TypeError):
        self.env["test.models.model"].browse(23)


def test_delete_cascade():
    """ Verify Cascaded deletion """
    tc1 = self.env["test.models.comodel"].create({"name": "Test"})
    tm1 = self.env["test.models.model"].create(
        {"name": "Test", "age": 10, "cascade_id": tc1._id})
    assert(tm1.cascade_id._id == tc1._id)
    tc1.unlink()
    assert(tm1.count() == 0)


def test_delete_restrict():
    """ Verify Restricted deletion """
    tc1 = self.env["test.models.comodel"].create({"name": "Test"})
    tm1 = self.env["test.models.model"].create(
        {"name": "Test", "age": 10, "restrict_id": tc1._id})
    assert(tm1.restrict_id._id == tc1._id)
    with pytest.raises(DeletionConstraintError):
        tc1.unlink()
    tm1.write({"restrict_id": None})
    assert(tc1.unlink() == 1)
    assert(tc1.count() == 0)


def test_delete_set_null():
    """ Verify Set Null on deletion """
    tc1 = self.env["test.models.comodel"].create({"name": "Test"})
    tm1 = self.env["test.models.model"].create(
        {"name": "Test", "age": 10, "setnull_id": tc1._id})
    assert(tm1.setnull_id._id == tc1._id)
    tc1.unlink()
    assert(tm1.setnull_id == None)


def test_read():
    """ Ensure read values are correct """
    tc1 = self.env["test.models.comodel"].create({"name": "Test_01"})
    tc2 = self.env["test.models.comodel"].create({"name": "Test_02"})
    tm1 = self.env["test.models.model"].create(
        {"name": "Test", "age": 10, "setnull_id": tc1._id})
    # Perform x2many write in a separate operation
    tm1.write({"onetomany_ids": [("replace", [tc1._id, tc2._id])]})
    tm1.write({"manytomany_ids": [("replace", [tc1._id, tc2._id])]})
    read = tm1.read()
    assert(read[0]["name"] == "Test")
    assert(read[0]["age"] == 10)
    # Test Many2one
    assert(read[0]["setnull_id"][0] == tc1._id)
    # Test One2many
    assert(len(read[0]["onetomany_ids"]) == 2)
    assert((tc1._id, tc1.name) in read[0]["onetomany_ids"])
    assert((tc2._id, tc2.name) in read[0]["onetomany_ids"])
    # Test Many2many
    assert(len(read[0]["manytomany_ids"]) == 2)
    assert((tc1._id, tc1.name) in read[0]["manytomany_ids"])
    assert((tc2._id, tc2.name) in read[0]["manytomany_ids"])

def test_mapped():
    """ Test mapped method """
    c1 = self.env["test.models.comodel"].create({"name": "MapComodel01"})
    c2 = self.env["test.models.comodel"].create({"name": "MapComodel02"})
    self.env["test.models.model"].create({"name": "Map01", "cascade_id": c1._id})
    self.env["test.models.model"].create({"name": "Map02", "cascade_id": c2._id})
    docset = self.env["test.models.model"].search({"name": {"$regex": "^Map"}})
    mapped = docset.mapped("name")
    assert(isinstance(mapped, list))
    assert(len(mapped) == docset.count())
    assert("Map01" in mapped)
    assert("Map02" in mapped)
    docset = docset.mapped("cascade_id")
    assert(c1._id in docset.ids())
    assert(c2._id in docset.ids())

def test_filtered():
    """ Test filtered method """
    o1 = self.env["test.models.model"].create({"name": "Filtered01", "age": 10})
    o2 = self.env["test.models.model"].create({"name": "Filtered02", "age": 20})
    o3 = self.env["test.models.model"].create({"name": "Filtered03", "age": 30})
    o4 = self.env["test.models.model"].create({"name": "Filtered04", "age": 40})
    docset = self.env["test.models.model"].search({"name": {"$regex": "^Filtered"}})
    docset = docset.filtered({"age": {"$gt": 25}})
    assert(isinstance(docset, Model))
    assert(len(docset) == 2)
    assert(o1 not in docset)
    assert(o2 not in docset)
    assert(o3 in docset)
    assert(o4 in docset)
    

def test_model_finish():
    """ Clean previous tests """
    conn = db.Connection()
    conn.db["test.models.model"].drop()
    conn.db["test.models.comodel"].drop()
    conn.db["test.model.comodel.rel"].drop()
    # Delete records generated by importations
    conn.db["base.model.data"].delete_many({"model": "test.models.model"})
