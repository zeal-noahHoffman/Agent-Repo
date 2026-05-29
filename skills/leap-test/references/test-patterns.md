# Platform-Specific Test Patterns

Default patterns by platform. **Always prefer the project's actual patterns** over these defaults — the existing test analysis in Phase 2 takes priority.

## Swift (Swift Testing)

```swift
import Testing
@testable import MyApp

struct FeatureNameTests {
    @Test func featureBehavior_whenCondition_doesExpectedThing() async throws {
        // Given
        // When
        // Then — use #expect(...)
    }
}
```

## Swift (XCTest)

```swift
import XCTest
@testable import MyApp

final class FeatureNameTests: XCTestCase {
    func test_featureBehavior_whenCondition_thenExpected() {
        // Given / When / Then — use XCTAssertEqual, etc.
    }
}
```

## Kotlin (JUnit 5 + MockK)

```kotlin
class FeatureNameTest {
    @MockK private lateinit var dependency: DependencyType
    private lateinit var sut: SystemUnderTest

    @BeforeEach
    fun setUp() {
        MockKAnnotations.init(this)
        sut = SystemUnderTest(dependency)
    }

    @Test
    fun `feature behavior when condition then expected`() {
        // Given / When / Then
    }
}
```

## TypeScript (Vitest / Jest)

```typescript
describe('FeatureName', () => {
    it('should do expected thing when condition', () => {
        // Arrange / Act / Assert
    });
});
```
