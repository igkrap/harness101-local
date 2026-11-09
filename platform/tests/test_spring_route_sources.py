"""Read-only source facts; no Java compilation, model calls, or application writes."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-only/harness'))
import spring_route_sources as routes

IMPORTS = 'package org.example.orders;\nimport org.springframework.web.bind.annotation.*;\n'


class SpringRouteSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.directory = self.root / 'backend/src/main/java/org/example/orders'
        self.directory.mkdir(parents=True)

    def put(self, name, source):
        path = self.directory / name
        path.write_text(source, encoding='utf-8')
        return path

    def test_class_literal_collections_resolve_arbitrary_filename_and_hash(self):
        path = self.put('Endpoints.java', IMPORTS + '''
@RestController
@RequestMapping(path={"/api/orders", "/api/order-search"})
class OrderRoutes { @GetMapping public String find(){return "ok";} }
''')
        before = path.read_bytes()
        for route in ('/api/orders', '/api/order-search'):
            found = routes.route_owners(self.root, route)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0], {'source': path.relative_to(self.root).as_posix(),
                'sha256': hashlib.sha256(before).hexdigest(), 'class_name': 'org.example.orders.OrderRoutes',
                'matched_routes': [route], 'match_kind': 'class-base'})
        self.assertEqual(path.read_bytes(), before)

    def test_method_paths_combine_with_bases_without_filtering_http_method(self):
        self.put('Routes.java', IMPORTS + '''
@RestController @RequestMapping(value={"/api/orders", "/api/records"}, produces="application/json")
class OrderRoutes {
 @GetMapping(path={"/search", "/list"})
 public String find(@RequestParam(required=false) String code){return code;}
}
''')
        for route in ('/api/orders/search', '/api/orders/list', '/api/records/search'):
            self.assertEqual(routes.route_owners(self.root, route)[0]['match_kind'], 'method-path')
        # A POST task can target this existing GET controller; no verb input is required.
        self.assertEqual(len(routes.route_owners(self.root, '/api/orders')), 1)

    def test_fully_qualified_annotations_and_method_only_absolute_paths(self):
        self.put('Endpoints.java', '''package org.example;
@org.springframework.web.bind.annotation.RestController
class Endpoints {
 @org.springframework.web.bind.annotation.RequestMapping(value="/api/orders", method=org.springframework.web.bind.annotation.RequestMethod.GET)
 public String find(){return "ok";}
}
''')
        found = routes.route_owners(self.root, '/api/orders')
        self.assertEqual(found[0]['class_name'], 'org.example.Endpoints')
        self.assertEqual(found[0]['match_kind'], 'method-path')

    def test_external_same_name_annotations_or_unknown_wildcards_do_not_claim_spring_routes(self):
        sources = [
            'import external.RestController; import external.RequestMapping; @RestController @RequestMapping("/api/orders") class Endpoints {}',
            'import org.springframework.web.bind.annotation.RestController; import external.RequestMapping; @RestController @RequestMapping("/api/orders") class Endpoints {}',
            'import org.springframework.web.bind.annotation.*; import external.*; @RestController @RequestMapping("/api/orders") class Endpoints {}',
        ]
        for source in sources:
            with self.subTest(source=source):
                self.put('Endpoints.java', source)
                self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])

    def test_explicit_spring_import_wins_over_unrelated_wildcard(self):
        self.put('Endpoints.java', '''
import external.*;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestMapping;
@RestController @RequestMapping("/api/orders") class Endpoints {}
''')
        self.assertEqual(len(routes.route_owners(self.root, '/api/orders')), 1)

    def test_nested_custom_mapping_and_same_unit_controller_names_do_not_claim_spring_identity(self):
        self.put('Endpoints.java', IMPORTS + '''
@RestController @RequestMapping("/api") class Endpoints {
 @interface GetMapping { String value(); }
 @GetMapping("/orders") public String find(){return "ok";}
}
''')
        self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])
        self.put('Endpoints.java', IMPORTS + '''
@interface RestController {}
@RestController @RequestMapping("/api/orders") class Endpoints {}
''')
        self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])

    def test_same_package_custom_annotation_shadows_spring_wildcard_but_not_explicit_import(self):
        self.put('Custom.java', 'package org.example.orders; @interface GetMapping { String value(); }')
        self.put('Endpoints.java', IMPORTS + '''
@RestController class Endpoints { @GetMapping("/api/orders") public String find(){return "ok";} }
''')
        self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])
        self.put('Endpoints.java', 'package org.example.orders;\n'
            'import org.springframework.web.bind.annotation.RestController;\n'
            'import org.springframework.web.bind.annotation.GetMapping;\n'
            '@RestController class Endpoints { @GetMapping("/api/orders") public String find(){return "ok";} }')
        self.assertEqual(len(routes.route_owners(self.root, '/api/orders')), 1)

    def test_static_imported_member_annotations_and_unknown_static_wildcards_are_not_spring_bindings(self):
        for imported in ('import static custom.Annotations.GetMapping;', 'import static custom.Annotations.*;'):
            with self.subTest(imported=imported):
                self.put('Endpoints.java', IMPORTS + imported + '''
@RestController @RequestMapping("/api") class Endpoints {
 @GetMapping("/orders") public String find(){return "ok";}
}
''')
                self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])

    def test_unresolved_class_mapping_and_inheritance_do_not_turn_into_an_empty_base(self):
        self.put('Endpoints.java', '''
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.*;
import static custom.Annotations.RequestMapping;
@RestController @RequestMapping("/unknown") class Endpoints {
 @GetMapping("/api/orders") public String find(){return "ok";}
}
''')
        self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])
        self.put('Endpoints.java', IMPORTS + '''
@RestController class Endpoints extends UnknownBase {
 @GetMapping("/api/orders") public String find(){return "ok";}
}
''')
        self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])

    def test_comments_strings_chars_and_textblocks_cannot_supply_annotations(self):
        self.put('Endpoints.java', IMPORTS + '''
// @RestController @RequestMapping("/api/orders") class Commented {}
/* @RestController @RequestMapping("/api/orders") class BlockCommented {} */
@RestController class Real {
 String text = "@RequestMapping(\\\"/api/orders\\\")";
 char marker = '@';
 String multiline = """
 @GetMapping("/api/orders") public String fake(){return "ok";}
 """;
 public String actual(){return "@GetMapping(\\\"/api/orders\\\")";}
}
''')
        self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])

    def test_dynamic_constant_concat_placeholder_escaped_and_textblock_paths_are_unsupported(self):
        expressions = ['BASE', '"/api/" + "orders"', '"${api.prefix}/orders"', '"#{api.prefix}/orders"',
                       r'"/api/\u006frders"', r'"/api/ord\ers"', '"""\n/api/orders\n"""']
        for expression in expressions:
            with self.subTest(expression=expression):
                self.put('Endpoints.java', IMPORTS + '@RestController @RequestMapping(' + expression + ') class Endpoints {}')
                self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])

    def test_dynamic_method_paths_do_not_hide_the_known_literal_class_base(self):
        self.put('Endpoints.java', IMPORTS + '''
@RestController @RequestMapping("/api/orders") class Endpoints {
 @GetMapping(METHOD_PATH) public String dynamic(){return "ok";}
 @GetMapping("/{id}") public String parameter(){return "ok";}
}
''')
        self.assertEqual(len(routes.route_owners(self.root, '/api/orders')), 1)
        for route in ('/api/orders/new', '/api/orders/123', '/api/orders/{id}'):
            self.assertEqual(routes.route_owners(self.root, route), [])

    def test_new_subroutes_similar_prefixes_query_strings_and_external_urls_are_not_guessed(self):
        self.put('Endpoints.java', IMPORTS + '@RestController @RequestMapping("/api/orders") class Endpoints {}')
        for route in ('/api/orders/new', '/api/orders-old', '/api/order', '/assets/orders.js',
                      '/api/orders?code=1', 'https://example.com/api/orders', '../api/orders', '/api/../orders'):
            with self.subTest(route=route):
                self.assertEqual(routes.route_owners(self.root, route), [])

    def test_multiple_exact_owners_are_returned_as_ambiguity_not_collapsed_by_file(self):
        self.put('Endpoints.java', IMPORTS + '''
@RestController @RequestMapping("/api/orders") class One {}
@RestController @RequestMapping("/api/orders") class Two {}
''')
        found = routes.route_owners(self.root, '/api/orders')
        self.assertEqual({entry['class_name'] for entry in found}, {'org.example.orders.One', 'org.example.orders.Two'})
        self.put('Other.java', IMPORTS + '@RestController @RequestMapping("/api/orders") class Three {}')
        self.assertEqual(len(routes.route_owners(self.root, '/api/orders')), 3)

    def test_only_backend_main_java_sources_are_considered(self):
        text = IMPORTS + '@RestController @RequestMapping("/api/orders") class Endpoints {}'
        for relative in ('backend/src/test/java/TestController.java', 'frontend/src/Fake.java', 'external/Controller.java'):
            target = self.root / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text)
        self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])

    def test_file_directory_and_project_symlinks_are_not_followed(self):
        outside = self.root / 'outside'; outside.mkdir()
        (outside / 'Endpoints.java').write_text(IMPORTS + '@RestController @RequestMapping("/api/orders") class Endpoints {}')
        (self.directory / 'Linked.java').symlink_to(outside / 'Endpoints.java')
        (self.directory / 'linked').symlink_to(outside, target_is_directory=True)
        self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])
        alias = self.root / 'project-alias'; alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(routes.route_owners(alias, '/api/orders'), [])

    def test_unclosed_syntax_and_resource_bounds_fail_closed(self):
        self.put('Endpoints.java', IMPORTS + '@RestController @RequestMapping("/api/orders") class Endpoints {}')
        self.put('Malformed.java', '/* @RequestMapping("/api/orders")')
        self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])
        (self.directory / 'Malformed.java').unlink()
        with patch.object(routes, 'MAX_SOURCE_BYTES', 5):
            self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])
        with patch.object(routes, 'MAX_FILES', 0):
            self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])
        with patch.object(routes, 'MAX_TOTAL_BYTES', 1):
            self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])

    def test_incomplete_import_declarations_fall_back_without_crashing(self):
        self.put('Endpoints.java', IMPORTS + '@RestController @RequestMapping("/api/orders") class Endpoints {}')
        for source in ('import', 'import static', 'package org.example.orders; import'):
            with self.subTest(source=source):
                self.put('Malformed.java', source)
                self.assertEqual(routes.route_owners(self.root, '/api/orders'), [])


if __name__ == '__main__':
    unittest.main()
