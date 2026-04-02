def test_require_board_access_respects_role_hierarchy(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]

    owner = models.User(email="owner@example.com", password_hash="x", display_name="Owner")
    editor = models.User(email="editor@example.com", password_hash="x", display_name="Editor")
    viewer = models.User(email="viewer@example.com", password_hash="x", display_name="Viewer")
    outsider = models.User(email="outsider@example.com", password_hash="x", display_name="Outsider")
    db.add_all([owner, editor, viewer, outsider])
    db.commit()

    board = main.create_board(main.BoardCreate(name="Shared Board"), db)
    board_row = db.query(models.Board).filter(models.Board.id == board["id"]).first()
    board_row.owner_user_id = owner.id
    main.ensure_board_membership(board_row, owner, "owner", db)
    main.ensure_board_membership(board_row, editor, "editor", db)
    main.ensure_board_membership(board_row, viewer, "viewer", db)
    db.commit()

    assert main.require_board_access(board_row.id, owner, db, "owner") == "owner"
    assert main.require_board_access(board_row.id, editor, db, "viewer") == "editor"
    assert main.require_board_access(board_row.id, editor, db, "editor") == "editor"
    assert main.require_board_access(board_row.id, viewer, db, "viewer") == "viewer"

    try:
        main.require_board_access(board_row.id, viewer, db, "editor")
        assert False, "Expected viewer editor access to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 403

    try:
        main.require_board_access(board_row.id, outsider, db, "viewer")
        assert False, "Expected outsider access to be denied"
    except main.HTTPException as exc:
        assert exc.status_code == 403


def test_first_registered_user_claims_legacy_boards(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]

    legacy_board = main.create_board(main.BoardCreate(name="Legacy Board"), db)
    legacy_row = db.query(models.Board).filter(models.Board.id == legacy_board["id"]).first()
    assert legacy_row.owner_user_id is None
    assert db.query(models.BoardMembership).count() == 0

    response = main.Response()
    user = main.auth_register(
        main.RegisterRequest(
            email="first@example.com",
            password="supersecret",
            display_name="First User",
        ),
        response,
        db,
    )

    db.refresh(legacy_row)
    membership = (
        db.query(models.BoardMembership)
        .filter(models.BoardMembership.board_id == legacy_row.id)
        .first()
    )

    assert user["id"] == legacy_row.owner_user_id
    assert membership is not None
    assert membership.user_id == user["id"]
    assert membership.role == "owner"


def test_owner_membership_backfills_from_existing_owner_user_id(app_env):
    main = app_env["main"]
    db = app_env["db"]
    models = app_env["models"]

    owner = models.User(email="owner2@example.com", password_hash="x", display_name="Owner Two")
    db.add(owner)
    db.commit()

    board = main.create_board(main.BoardCreate(name="Owned Board"), db)
    board_row = db.query(models.Board).filter(models.Board.id == board["id"]).first()
    board_row.owner_user_id = owner.id
    db.commit()

    assert db.query(models.BoardMembership).count() == 0

    main._migrate_board_memberships()

    membership = (
        db.query(models.BoardMembership)
        .filter(
            models.BoardMembership.board_id == board_row.id,
            models.BoardMembership.user_id == owner.id,
        )
        .first()
    )
    assert membership is not None
    assert membership.role == "owner"
