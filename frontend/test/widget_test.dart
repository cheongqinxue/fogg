import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_map/flutter_map.dart';

import 'package:fogg/main.dart';

void main() {
  testWidgets('map screen shows FOGG title and FlutterMap', (WidgetTester tester) async {
    await tester.pumpWidget(const FoggApp());
    await tester.pump();

    expect(find.text('FOGG'), findsOneWidget);
    expect(find.byType(FlutterMap), findsOneWidget);
  });
}
