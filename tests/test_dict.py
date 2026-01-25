import unittest
import tempfile
import os
import sys
import json
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/concierge_acpi')

from persistent_dictionary import OptionallyPersistentOrderedThreadSafeDict, FullDictionaryError


class TestOptionallyPersistentOrderedThreadSafeDict(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_file = os.path.join(self.temp_dir, "test_db")

    def tearDown(self):
        # Clean up temp files
        for file in os.listdir(self.temp_dir):
            try:
                os.remove(os.path.join(self.temp_dir, file))
            except Exception:
                pass
        try:
            os.rmdir(self.temp_dir)
        except Exception:
            pass

    def test_init_in_memory(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        self.assertEqual(len(d), 0)
        self.assertIsNone(d._filepath)

    def test_init_with_file(self):
        d = OptionallyPersistentOrderedThreadSafeDict(self.temp_file, 10)
        self.assertEqual(len(d), 0)
        self.assertEqual(d._filepath, self.temp_file)
        self.assertEqual(d._max_size, 10)

    def test_setitem_in_memory(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        d["key1"] = "value1"
        self.assertEqual(d["key1"], "value1")
        self.assertEqual(len(d), 1)

    def test_setitem_persistent(self):
        d = OptionallyPersistentOrderedThreadSafeDict(self.temp_file)
        d["key1"] = "value1"
        self.assertEqual(d["key1"], "value1")
        
        # Verify persistence
        d2 = OptionallyPersistentOrderedThreadSafeDict(self.temp_file)
        self.assertEqual(d2["key1"], "value1")

    def test_update_existing_key(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        d["key1"] = "value1"
        d["key1"] = "value2"
        self.assertEqual(d["key1"], "value2")
        self.assertEqual(len(d), 1)

    def test_getitem_missing_key(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        with self.assertRaises(KeyError):
            _ = d["missing"]

    def test_delitem_in_memory(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        d["key1"] = "value1"
        del d["key1"]
        self.assertEqual(len(d), 0)
        self.assertNotIn("key1", d)

    def test_delitem_persistent(self):
        d = OptionallyPersistentOrderedThreadSafeDict(self.temp_file)
        d["key1"] = "value1"
        del d["key1"]
        
        d2 = OptionallyPersistentOrderedThreadSafeDict(self.temp_file)
        self.assertNotIn("key1", d2)

    def test_contains(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        d["key1"] = "value1"
        self.assertIn("key1", d)
        self.assertNotIn("key2", d)

    def test_len(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        self.assertEqual(len(d), 0)
        d["key1"] = "value1"
        self.assertEqual(len(d), 1)
        d["key2"] = "value2"
        self.assertEqual(len(d), 2)

    def test_get_with_default(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        self.assertIsNone(d.get("missing"))
        self.assertEqual(d.get("missing", "default"), "default")
        d["key1"] = "value1"
        self.assertEqual(d.get("key1"), "value1")

    def test_keys(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        d["key1"] = "value1"
        d["key2"] = "value2"
        d["key3"] = "value3"
        keys = d.keys()
        self.assertEqual(keys, ["key1", "key2", "key3"])

    def test_order_maintained(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        d["c"] = 3
        d["a"] = 1
        d["b"] = 2
        self.assertEqual(d.keys(), ["c", "a", "b"])

    def test_order_updated_on_set(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        d["a"] = 1
        d["b"] = 2
        d["c"] = 3
        d["a"] = 10  # Update existing
        self.assertEqual(d.keys(), ["b", "c", "a"])

    def test_get_oldest_key(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        d["first"] = 1
        d["second"] = 2
        self.assertEqual(d.get_oldest_key(), "first")

    def test_get_oldest_key_empty(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        with self.assertRaises(KeyError):
            d.get_oldest_key()

    def test_get_newest(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        d["first"] = 1
        d["second"] = 2
        self.assertEqual(d.get_newest(), 2)

    def test_get_newest_empty(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        with self.assertRaises(KeyError):
            d.get_newest()

    def test_get_items_reversed(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        d["a"] = 1
        d["b"] = 2
        d["c"] = 3
        items = d.get_items_reversed()
        self.assertEqual(items, [3, 2, 1])

    def test_tag_for_removal(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        d["key1"] = "value1"
        d["key2"] = "value2"
        d.tag_for_removal("key1")
        self.assertIn("key1", d._tagged_for_removal)

    def test_tag_for_removal_persistent(self):
        d = OptionallyPersistentOrderedThreadSafeDict(self.temp_file)
        d["key1"] = "value1"
        d.tag_for_removal("key1")
        
        d2 = OptionallyPersistentOrderedThreadSafeDict(self.temp_file)
        self.assertIn("key1", d2._tagged_for_removal)

    def test_max_size_enforcement(self):
        d = OptionallyPersistentOrderedThreadSafeDict(None, 2)
        d["key1"] = "value1"
        d.tag_for_removal("key1")
        d["key2"] = "value2"
        d.tag_for_removal("key2")
        d["key3"] = "value3"  # Should remove key1
        
        self.assertNotIn("key1", d)
        self.assertIn("key2", d)
        self.assertIn("key3", d)

    def test_max_size_without_tagged_raises_error(self):
        d = OptionallyPersistentOrderedThreadSafeDict(None, 2)
        d["key1"] = "value1"
        d["key2"] = "value2"
        
        with self.assertRaises(FullDictionaryError):
            d["key3"] = "value3"

    def test_untagging_on_update(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        d["key1"] = "value1"
        d.tag_for_removal("key1")
        self.assertIn("key1", d._tagged_for_removal)
        
        d["key1"] = "value2"  # Update should untag
        self.assertNotIn("key1", d._tagged_for_removal)

    def test_thread_safety(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        errors = []
        
        def writer(key_range):
            try:
                for i in key_range:
                    d[f"key{i}"] = f"value{i}"
            except Exception as e:
                errors.append(e)
        
        threads = []
        for i in range(5):
            t = threading.Thread(target=writer, args=(range(i*10, (i+1)*10),))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(d), 50)

    def test_persistence_after_reload(self):
        d1 = OptionallyPersistentOrderedThreadSafeDict(self.temp_file)
        d1["key1"] = {"data": "value1"}
        d1["key2"] = {"data": "value2"}
        d1.tag_for_removal("key1")
        
        # Reload
        d2 = OptionallyPersistentOrderedThreadSafeDict(self.temp_file)
        self.assertEqual(d2["key1"], {"data": "value1"})
        self.assertEqual(d2["key2"], {"data": "value2"})
        self.assertEqual(d2.keys(), ["key1", "key2"])
        self.assertIn("key1", d2._tagged_for_removal)

    def test_metadata_file_creation(self):
        d = OptionallyPersistentOrderedThreadSafeDict(self.temp_file)
        d["key1"] = "value1"
        
        metadata_file = f"{self.temp_file}_metadata.json"
        self.assertTrue(os.path.exists(metadata_file))
        
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        self.assertEqual(metadata['order'], ["key1"])

    def test_get_exception_handling(self):
        d = OptionallyPersistentOrderedThreadSafeDict()
        # Should return default without raising exception
        result = d.get("nonexistent", "default")
        self.assertEqual(result, "default")


if __name__ == '__main__':
    unittest.main()
